"""Guarded Phase 6 AWS plan, acceptance run and state-owned teardown.

--plan-only makes a read-only AWS-backed plan. --execute requires a separate
approval environment flag and reuses that saved reviewed plan. --cleanup-only
destroys only the existing run's Terraform state resources and audits absence.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from build_phase6_lambda import OUTPUT as PACKAGE, build as build_package, check as check_package

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "infrastructure/terraform/phase6"
WORK = ROOT / ".data/phase6-cloud"
VARIABLES = WORK / "run.tfvars.json"
PLAN = WORK / "run.tfplan"
STATE = MODULE / "terraform.tfstate"
PLAN_EVIDENCE = ROOT / "docs/evidence/phase-6-cloud-plan.json"
EVIDENCE = ROOT / "docs/evidence/phase-6-cloud.json"
PROFILE = os.getenv("AWS_PROFILE", "smarttraffic-sdk")
REGION = os.getenv("AWS_REGION", "ap-south-1")
EXPECTED = Counter({"terraform_data": 1, "aws_sqs_queue": 2,
                    "aws_dynamodb_table": 1, "aws_cloudwatch_log_group": 1,
                    "aws_iam_role": 1, "aws_iam_role_policy": 1,
                    "aws_iam_policy": 2, "aws_lambda_function": 1,
                    "aws_lambda_event_source_mapping": 1})
BUDGET_CAP_USD = 8.00
RESERVED_CLEANUP_USD = 0.50
PREDEPLOYMENT_GATE_USD = BUDGET_CAP_USD - RESERVED_CLEANUP_USD


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def checkpoint_execution(evidence):
    """Persist accepted cloud evidence before a later cleanup stage can fail."""
    write_json(EVIDENCE, evidence)
    if evidence.get("run_name"):
        write_json(EVIDENCE.parent / f"phase-6-cloud-{evidence['run_name']}.json", evidence)


def resume_cleanup_evidence(run_name, base):
    """Keep prior acceptance proof when a later recovery-only cleanup is needed."""
    path = EVIDENCE.parent / f"phase-6-cloud-{run_name}.json"
    if not path.exists():
        return base
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    persisted.update(base)
    persisted["cleanup_resumed_at"] = base["started_at"]
    return persisted


def tf(*args, capture=False):
    process = subprocess.run(["terraform", f"-chdir={MODULE}", *args], cwd=ROOT,
                             env={**os.environ, "AWS_PROFILE": PROFILE, "AWS_REGION": REGION},
                             text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(f"Terraform {args[0]} failed: {process.stderr[-1800:]}")
    if not capture:
        print(process.stdout[-4000:])
    return process.stdout


def session():
    current = boto3.Session(profile_name=PROFILE, region_name=REGION)
    identity = current.client("sts").get_caller_identity()
    if REGION != "ap-south-1":
        raise RuntimeError("Phase 6 review approves only ap-south-1")
    return current, {"account": identity["Account"], "principal_arn": identity["Arn"],
                     "region": REGION}


def cost_preflight(current):
    today = dt.datetime.now(dt.UTC).date()
    start = today.replace(day=1).isoformat()
    end = (today + dt.timedelta(days=1)).isoformat()
    response = current.client("ce", region_name="us-east-1").get_cost_and_usage(
        TimePeriod={"Start": start, "End": end}, Granularity="MONTHLY",
        Metrics=["UnblendedCost"])
    amount = sum(float(period["Total"]["UnblendedCost"]["Amount"])
                 for period in response["ResultsByTime"])
    return {"start": start, "end_exclusive": end,
            "unblended_usd_estimate": round(amount, 6),
            "estimated_by_aws": any(period.get("Estimated", False)
                                    for period in response["ResultsByTime"]),
            "budget_cap_usd": BUDGET_CAP_USD,
            "required_reserve_usd": RESERVED_CLEANUP_USD,
            "below_predeployment_gate": amount < PREDEPLOYMENT_GATE_USD}


def get_variables():
    return json.loads(VARIABLES.read_text(encoding="utf-8"))


def review_plan_document(document):
    changes = [item for item in document.get("resource_changes", [])
               if item["change"]["actions"] != ["no-op"]]
    counts = Counter(item["type"] for item in changes)
    if counts != EXPECTED or any(item["change"]["actions"] != ["create"] for item in changes):
        raise RuntimeError(f"Plan is outside approved create-only scope: {counts}")
    return [{"address": item["address"], "type": item["type"],
             "actions": item["change"]["actions"]} for item in changes]


def plan_only():
    if STATE.exists() and tf("state", "list", capture=True).strip():
        raise RuntimeError("Phase 6 Terraform state is nonempty; clean the existing run first")
    build_package()
    package = check_package()
    project = "stp6-" + dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
    variables = {"deployment_approved": True, "aws_region": REGION,
                 "project_name": project}
    write_json(VARIABLES, variables)
    tf("plan", "-input=false", "-no-color", "-var-file=" + str(VARIABLES),
       "-out=" + str(PLAN))
    document = json.loads(tf("show", "-json", str(PLAN), capture=True))
    changes = review_plan_document(document)
    evidence = {"run_name": project, "profile": PROFILE, "region": REGION,
                "package_bytes": package["bytes"],
                "package_sha256": hashlib.sha256(PACKAGE.read_bytes()).hexdigest(),
                "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
                "changes": changes,
                "plan_only": True, "created_resources": False}
    write_json(PLAN_EVIDENCE, evidence)
    return evidence


def outputs():
    values = json.loads(tf("output", "-json", capture=True))
    return {name: item["value"] for name, item in values.items()}


def wait_for(check, label, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for {label}")


def all_log_events(client, group, *, maximum=1000):
    """CloudWatch may return an empty page while more pages remain."""
    events = []
    pages = client.get_paginator("filter_log_events").paginate(
        logGroupName=group, PaginationConfig={"PageSize": 1000})
    for page in pages:
        events.extend(page.get("events", []))
        if len(events) >= maximum:
            break
    return events[:maximum]


def request_pair(run_name):
    from traffic_contracts.alerts import congestion_request
    now = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
    end = now + dt.timedelta(minutes=1)
    start_text = now.isoformat().replace("+00:00", "Z")
    end_text = end.isoformat().replace("+00:00", "Z")
    intersection = run_name + "-intersection"
    window = f"{intersection}/{start_text}/{end_text}/v1"
    congestion = congestion_request({"congestion": "high", "window_id": window,
                                     "intersection_id": intersection, "window_end": end_text})
    event_id = str(uuid.uuid4())
    incident = {"schema_version": "1.0", "alert_id": event_id + "/incident-alert/v1",
                "source_type": "incident", "source_id": event_id,
                "intersection_id": intersection, "reason": "incident_closure_open",
                "occurred_at": end_text, "rule_version": "1"}
    return congestion, incident


def acceptance(current, values, evidence, *, logs_only=False):
    from traffic_contracts.alerts import canonical_body
    sqs = current.client("sqs")
    ddb = current.resource("dynamodb")
    table = ddb.Table(values["alert_table_name"])
    first, second = request_pair(evidence["run_name"])
    queue_url = values["alert_queue_url"]
    for request in (first, second):
        sqs.send_message(QueueUrl=queue_url, MessageBody=canonical_body(request))
    wait_for(lambda: all(table.get_item(Key={"alert_id": request["alert_id"]},
                                        ConsistentRead=True).get("Item", {}).get("outcome") == "recorded"
                         for request in (first, second)), "both DynamoDB alert outcomes")
    original = table.get_item(Key={"alert_id": first["alert_id"]},
                              ConsistentRead=True)["Item"]
    sqs.send_message(QueueUrl=queue_url, MessageBody=canonical_body(first))
    time.sleep(8)
    replayed = table.get_item(Key={"alert_id": first["alert_id"]},
                              ConsistentRead=True)["Item"]
    if replayed != original:
        raise RuntimeError("duplicate delivery changed the stored alert")
    evidence["paths"] = {"congestion": True, "incident": True,
                         "duplicate_preserved": True}
    checkpoint_execution(evidence)

    # A valid same-ID/different-content request must be retried. Full mode also
    # checks DLQ redrive and operator recovery; earlier run evidence can be reused
    # when a narrow log-verification rerun is authorized.
    conflict = {**second, "intersection_id": second["intersection_id"] + "-conflict"}
    body = canonical_body(conflict)
    sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    if not logs_only:
        print("Waiting for five SQS receives and DLQ redrive (up to eight minutes).")
        message = wait_for(lambda: (sqs.receive_message(QueueUrl=values["dlq_url"],
                                                        MaxNumberOfMessages=1,
                                                        WaitTimeSeconds=0,
                                                        MessageSystemAttributeNames=["ApproximateReceiveCount"])
                                    .get("Messages") or [None])[0],
                           "conflicting request in DLQ", seconds=480)
        if message["Body"] != body:
            raise RuntimeError("DLQ body differs from the original conflicting request")
        evidence["dlq"] = {"same_body": True, "receive_count": message.get("Attributes", {}).get("ApproximateReceiveCount")}
        # Operator recovery of the run-owned test record; replay preserves exact DLQ bytes.
        table.delete_item(Key={"alert_id": second["alert_id"]})
        sqs.send_message(QueueUrl=queue_url, MessageBody=message["Body"])
        wait_for(lambda: table.get_item(Key={"alert_id": second["alert_id"]},
                                        ConsistentRead=True).get("Item", {}).get("intersection_id")
                 == conflict["intersection_id"], "DLQ replay outcome")
        sqs.delete_message(QueueUrl=values["dlq_url"], ReceiptHandle=message["ReceiptHandle"])
        evidence["dlq"]["same_body_recovery"] = True

    logs = current.client("logs")
    group = "/aws/lambda/" + values["lambda_function_name"]
    def log_check():
        events = all_log_events(logs, group)
        text = "\n".join(item["message"] for item in events)
        conflicts = sum("AlertConflict" in item["message"] for item in events)
        evidence["log_observation"] = {
            "event_count": len(events),
            "congestion_id_present": first["alert_id"] in text,
            "incident_id_present": second["alert_id"] in text,
            "duplicate_info_present": "outcome=unchanged" in text,
            "conflict_retry_count": conflicts,
        }
        checkpoint_execution(evidence)
        return events if conflicts >= (1 if logs_only else 2) and all(marker in text for marker in
                         (first["alert_id"], second["alert_id"], "outcome=unchanged")) else None
    events = wait_for(log_check, "traceable Lambda logs")
    evidence["logs"] = {"group": group, "event_count": len(events),
                        "congestion": True, "incident": True,
                        "duplicate": True,
                        "conflict_retry_log_count": sum("AlertConflict" in item["message"]
                                                        for item in events)}
    evidence["managed_verified"] = True
    evidence["mode"] = "logs-only" if logs_only else "full"
    checkpoint_execution(evidence)


def missing(call, codes):
    try:
        call()
    except ClientError as error:
        return error.response.get("Error", {}).get("Code") in codes
    return False


def cleanup(current, evidence):
    evidence["teardown_requested"] = True
    checkpoint_execution(evidence)
    known = outputs() if STATE.exists() and tf("state", "list", capture=True).strip() else {}
    evidence["outputs_before_destroy"] = known
    checkpoint_execution(evidence)
    tf("destroy", "-auto-approve", "-input=false", "-no-color",
       "-var-file=" + str(VARIABLES))
    state = tf("state", "list", capture=True).strip() if STATE.exists() else ""
    evidence["terraform_state_empty"] = not state
    if state:
        raise RuntimeError("Terraform state remains nonempty after destroy")
    if known:
        sqs, ddb, lam, iam, logs = (current.client(name) for name in
                                    ("sqs", "dynamodb", "lambda", "iam", "logs"))
        def audit():
            checks = {
                "source_queue_absent": missing(lambda: sqs.get_queue_url(QueueName=evidence["run_name"] + "-alerts"),
                                               {"AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"}),
                "dlq_absent": missing(lambda: sqs.get_queue_url(QueueName=evidence["run_name"] + "-alerts-dlq"),
                                      {"AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"}),
                "table_absent": missing(lambda: ddb.describe_table(TableName=known["alert_table_name"]),
                                        {"ResourceNotFoundException"}),
                "function_absent": missing(lambda: lam.get_function(FunctionName=known["lambda_function_name"]),
                                           {"ResourceNotFoundException"}),
                "mapping_absent": missing(lambda: lam.get_event_source_mapping(UUID=known["event_source_mapping_uuid"]),
                                          {"ResourceNotFoundException"}),
                "role_absent": missing(lambda: iam.get_role(RoleName=evidence["run_name"] + "-alert-lambda"),
                                       {"NoSuchEntity"}),
                "signal_policy_absent": missing(lambda: iam.get_policy(PolicyArn=known["signal_recommendation_send_policy_arn"]),
                                                {"NoSuchEntity"}),
                "incident_policy_absent": missing(lambda: iam.get_policy(PolicyArn=known["incident_manager_send_policy_arn"]),
                                                  {"NoSuchEntity"}),
                "log_group_absent": not logs.describe_log_groups(logGroupNamePrefix="/aws/lambda/" +
                                                                   known["lambda_function_name"]).get("logGroups"),
            }
            evidence["absence_audit"] = checks
            return checks if all(checks.values()) else None
        checks = wait_for(audit, "run-owned resource absence", seconds=90)
        evidence["absence_audit"] = checks
    checkpoint_execution(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--logs-only", action="store_true",
                        help="With --execute, repeat only the missing cloud log checks")
    args = parser.parse_args()
    if args.logs_only and not args.execute:
        parser.error("--logs-only requires --execute")
    if args.execute and os.getenv("PHASE6_CLOUD_DEPLOYMENT_APPROVED") != "yes":
        parser.error("--execute requires PHASE6_CLOUD_DEPLOYMENT_APPROVED=yes after explicit user approval")
    if (args.execute or args.cleanup_only) and not VARIABLES.exists():
        parser.error("No reviewed Phase 6 run variables exist")

    WORK.mkdir(parents=True, exist_ok=True)
    evidence = {"started_at": dt.datetime.now(dt.UTC).isoformat(),
                "managed_verified": False, "profile": PROFILE, "region": REGION}
    if args.cleanup_only:
        evidence = resume_cleanup_evidence(get_variables()["project_name"], evidence)
    current = None
    error = None
    try:
        current, identity = session()
        evidence["identity"] = identity
        try:
            evidence["cost_preflight"] = cost_preflight(current)
        except Exception as exc:
            evidence["cost_preflight"] = {"unavailable": type(exc).__name__}
        if args.execute and not evidence["cost_preflight"].get("below_predeployment_gate"):
            raise RuntimeError("Current account spend was unavailable or lacks the US$0.50 reserve below the US$8 cap")
        tf("init", "-backend=false", "-input=false", "-no-color")
        if args.plan_only:
            evidence.update(plan_only())
            print("PLAN ONLY: no AWS resources created")
        else:
            variables = get_variables()
            evidence["run_name"] = variables["project_name"]
            if args.execute:
                reviewed = json.loads(PLAN_EVIDENCE.read_text(encoding="utf-8"))
                if reviewed["run_name"] != evidence["run_name"] or not PLAN.exists():
                    raise RuntimeError("saved plan/run name does not match the reviewed plan")
                if hashlib.sha256(PLAN.read_bytes()).hexdigest() != reviewed["plan_sha256"]:
                    raise RuntimeError("saved Terraform plan changed after review")
                check_package()
                if hashlib.sha256(PACKAGE.read_bytes()).hexdigest() != reviewed["package_sha256"]:
                    raise RuntimeError("Lambda package changed after the reviewed plan")
                tf("apply", "-input=false", "-no-color", str(PLAN))
                evidence["deployment_applied"] = True
                checkpoint_execution(evidence)
                acceptance(current, outputs(), evidence, logs_only=args.logs_only)
                print("PASS: alert paths, duplicate and Lambda logs" +
                      (" (DLQ evidence from prior run)" if args.logs_only else ", DLQ recovery"))
            else:
                cleanup(current, evidence)
    except BaseException as exc:
        evidence["failure"] = str(exc)
        traceback.print_exc()
        error = exc
    finally:
        if current is not None and args.execute:
            try:
                cleanup(current, evidence)
            except BaseException as exc:
                evidence["cleanup_failure"] = str(exc)
                traceback.print_exc()
                error = error or exc
        evidence["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
        if args.plan_only:
            write_json(PLAN_EVIDENCE, evidence)
        else:
            checkpoint_execution(evidence)
        if VARIABLES.exists() and evidence.get("terraform_state_empty"):
            variables = get_variables()
            variables["deployment_approved"] = False
            write_json(VARIABLES, variables)
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "contracts/python"))
    main()
