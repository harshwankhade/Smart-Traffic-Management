"""Guarded, temporary AWS DynamoDB verification for Phase 5.

This runner owns exactly two run-named DynamoDB tables and two unattached IAM policies.
It refuses an apply unless a future, explicitly approved invocation provides both --execute
and PHASE5_MANAGED_DEPLOYMENT_APPROVED=yes. Its finally path destroys only Terraform state
resources and checks that the two tables and policies no longer exist.
"""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "infrastructure" / "terraform" / "phase5"
WORK = ROOT / ".data" / "phase5-managed"
VARIABLES = WORK / "run.tfvars.json"
PLAN_EVIDENCE = ROOT / "docs" / "evidence" / "phase-5-managed-plan.json"
EVIDENCE = ROOT / "docs" / "evidence" / "phase-5-managed.json"
REGION = os.getenv("AWS_REGION", "ap-south-1")
PROFILE = os.getenv("AWS_PROFILE", "smarttraffic-sdk")
EXPECTED_TYPES = {"terraform_data", "aws_dynamodb_table", "aws_iam_policy"}


def tf(*args, capture=False):
    command = ["terraform", f"-chdir={MODULE}", *args]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=capture,
                               env={**os.environ, "AWS_REGION": REGION, "AWS_PROFILE": PROFILE})
    if not capture:
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
    if completed.returncode:
        raise RuntimeError("Terraform command failed: " + " ".join(args[:2]))
    return completed.stdout


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def session_and_preflight():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    identity = session.client("sts").get_caller_identity()
    limits = session.client("dynamodb").describe_limits()
    return session, {"account": identity["Account"], "principal_arn": identity["Arn"],
                     "region": REGION, "dynamodb_limits_checked": bool(limits)}


def new_variables():
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return {"deployment_approved": False, "aws_region": REGION, "project_name": f"stp5-{stamp}"}


def reviewed_plan():
    plan_file = WORK / "run.tfplan"
    tf("plan", "-input=false", "-no-color", "-var-file=" + str(VARIABLES), "-out=" + str(plan_file))
    document = json.loads(tf("show", "-json", str(plan_file), capture=True))
    changes = [item for item in document.get("resource_changes", [])
               if item["change"]["actions"] != ["no-op"]]
    unexpected = [item["address"] for item in changes if item["type"] not in EXPECTED_TYPES]
    destructive = [item["address"] for item in changes if any(action in {"delete", "update"}
                                                                  for action in item["change"]["actions"])]
    table_changes = [item for item in changes if item["type"] == "aws_dynamodb_table"]
    policy_changes = [item for item in changes if item["type"] == "aws_iam_policy"]
    if unexpected or destructive or len(table_changes) != 2 or len(policy_changes) != 2:
        raise RuntimeError("Plan is outside the two-table/two-policy managed verification scope")
    return plan_file, [{"address": item["address"], "type": item["type"],
                        "actions": item["change"]["actions"]} for item in changes]


def outputs():
    return json.loads(tf("output", "-json", capture=True))


def output_values():
    return {name: item["value"] for name, item in outputs().items()}


def run_service_code_test(values, project):
    env = {**os.environ, "AWS_REGION": REGION, "AWS_PROFILE": PROFILE,
           "RECOMMENDATIONS_TABLE": values["recommendations_table"],
           "SUMMARIES_TABLE": values["summaries_table"], "PHASE5_MANAGED_RUN_ID": project,
           "PHASE5_MANAGED_DYNAMODB_TEST": "1"}
    env.pop("DYNAMODB_ENDPOINT_URL", None)
    completed = subprocess.run([sys.executable, "-m", "unittest", "tests.test_phase5_managed", "-v"],
                               cwd=ROOT, env=env, text=True)
    if completed.returncode:
        raise RuntimeError("Managed service-code DynamoDB test failed")


def absent(call):
    try:
        call()
    except ClientError as error:
        return error.response.get("Error", {}).get("Code") in {"ResourceNotFoundException", "NoSuchEntity"}
    return False


def cleanup(session, evidence):
    evidence["teardown_requested"] = True
    known = output_values() if tf("state", "list", capture=True).strip() else {}
    evidence["state_outputs_before_destroy"] = known
    errors = []
    try:
        tf("destroy", "-auto-approve", "-input=false", "-no-color", "-var-file=" + str(VARIABLES))
    except Exception as error:
        errors.append("terraform destroy: " + str(error))
    remaining = tf("state", "list", capture=True).strip()
    evidence["terraform_state_empty_after_teardown"] = not remaining
    if remaining:
        errors.append("Terraform state still has resources: " + remaining)
    ddb = session.client("dynamodb")
    iam = session.client("iam")
    table_names = [known.get("recommendations_table"), known.get("summaries_table")]
    policy_arns = [known.get("signal_recommendation_policy_arn"),
                   known.get("traffic_analytics_policy_arn")]
    evidence["tables_absent_after_teardown"] = all(name and absent(
        lambda table=name: ddb.describe_table(TableName=table)) for name in table_names)
    evidence["policies_absent_after_teardown"] = all(arn and absent(
        lambda policy_arn=arn: iam.get_policy(PolicyArn=policy_arn)) for arn in policy_arns)
    if not evidence["tables_absent_after_teardown"]:
        errors.append("A run-owned DynamoDB table remains")
    if not evidence["policies_absent_after_teardown"]:
        errors.append("A run-owned IAM policy remains")
    if errors:
        evidence["cleanup_errors"] = errors
        raise RuntimeError("; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    if args.execute and os.getenv("PHASE5_MANAGED_DEPLOYMENT_APPROVED") != "yes":
        parser.error("--execute requires PHASE5_MANAGED_DEPLOYMENT_APPROVED=yes after explicit user approval")

    WORK.mkdir(parents=True, exist_ok=True)
    if args.cleanup_only:
        if not VARIABLES.exists():
            raise RuntimeError("No run variables exist for cleanup")
        variables = json.loads(VARIABLES.read_text(encoding="utf-8"))
    else:
        variables = new_variables()
        # An AWS-backed plan is read-only. The module's guard must be true to
        # inspect its exact future creates, but only --execute can reach apply.
        if args.plan_only or args.execute:
            variables["deployment_approved"] = True
        write_json(VARIABLES, variables)

    evidence = {"run_name": variables["project_name"], "scope": "two temporary DynamoDB tables and two policies",
                "managed_verified": False, "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    session = None
    error = None
    try:
        session, preflight = session_and_preflight()
        evidence["access_preflight"] = preflight
        tf("init", "-backend=false", "-input=false", "-no-color")
        if args.cleanup_only:
            cleanup(session, evidence)
            return
        plan_file, summary = reviewed_plan()
        evidence["reviewed_plan"] = summary
        if args.plan_only:
            print("PLAN ONLY: no AWS resources created")
            return
        tf("apply", "-input=false", "-no-color", str(plan_file))
        values = output_values()
        evidence["run_outputs"] = values
        run_service_code_test(values, variables["project_name"])
        evidence["managed_verified"] = True
        print("PASS managed DynamoDB service-code read/write/replay verification")
    except BaseException as exc:
        evidence["failure"] = str(exc)
        traceback.print_exc()
        error = exc
    finally:
        if session is not None and args.execute:
            try:
                cleanup(session, evidence)
            except BaseException as exc:
                evidence["cleanup_failure"] = str(exc)
                traceback.print_exc()
                error = error or exc
        evidence["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_json(PLAN_EVIDENCE if args.plan_only else EVIDENCE, evidence)
        if VARIABLES.exists() and (args.plan_only or evidence.get("terraform_state_empty_after_teardown")):
            variables["deployment_approved"] = False
            write_json(VARIABLES, variables)
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
