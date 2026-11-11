"""Deploy, verify and tear down the temporary Phase 4 EMR on EC2 stack.

The runner owns only the uniquely named Terraform stack recorded under .data. It always
attempts teardown after a deployment attempt and never deletes an unrelated bucket or cluster.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "infrastructure/terraform/phase4-live"
WORK = ROOT / ".data/phase4-cloud"
VARIABLES = WORK / "run.tfvars.json"
EVIDENCE = ROOT / "docs/evidence/phase-4-cloud.json"
PLAN_EVIDENCE = ROOT / "docs/evidence/phase-4-plan.json"
PROFILE = "smarttraffic-sdk"
REGION = "ap-south-1"
ENV = {**os.environ, "AWS_PROFILE": PROFILE, "AWS_REGION": REGION,
       "AWS_DEFAULT_REGION": REGION, "AWS_SDK_LOAD_CONFIG": "1", "TF_IN_AUTOMATION": "1"}


def tf(*args, capture=False, timeout=4200):
    result = subprocess.run(["terraform", "-chdir=" + str(MODULE), *args], env=ENV,
                            text=True, capture_output=True, timeout=timeout)
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "terraform.log").open("a", encoding="utf-8") as log:
        log.write("\nCOMMAND " + " ".join(args) + "\n" + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-16000:], flush=True)
        raise RuntimeError("Terraform command failed: " + " ".join(args[:2]))
    return result.stdout if capture else None


def state_outputs():
    raw = json.loads(tf("output", "-json", capture=True))
    return {key: value["value"] for key, value in raw.items()}


def choose_run_variables(existing, reuse_reviewed_run, reviewed):
    if reuse_reviewed_run:
        run_name = existing.get("project_name")
        if (existing.get("deployment_approved") or not run_name or
                reviewed.get("run_name") != run_name or not reviewed.get("reviewed_plan")):
            raise RuntimeError("Refusing to reuse a run without matching completed plan-only evidence and a disabled guard")
        return {**existing, "deployment_approved": True}
    return {"deployment_approved": True, "project_name": "stp4-" + uuid4().hex[:10]}


def kafka_service_role_before(session):
    """Record whether the shared MSK service-linked role predates this run."""
    iam = session.client("iam")
    try:
        role = iam.get_role(RoleName="AWSServiceRoleForKafka")["Role"]
    except iam.exceptions.NoSuchEntityException:
        return {"present": False}
    if role["Path"] != "/aws-service-role/kafka.amazonaws.com/":
        raise RuntimeError("Unexpected Kafka service-linked role path")
    return {"present": True}


def state_emr_security_groups():
    """Return only EMR security groups already recorded in this run's state."""
    document = json.loads(tf("show", "-json", capture=True))
    found = {}

    def visit(module):
        for resource in module.get("resources", []):
            address = resource.get("address", "")
            if resource.get("type") == "aws_security_group" and address.startswith(
                    "module.processing.aws_security_group.emr_"):
                resource_id = resource.get("values", {}).get("id")
                if resource_id:
                    found[address] = resource_id
        for child in module.get("child_modules", []):
            visit(child)

    root_module = document.get("values", {}).get("root_module")
    if root_module:
        visit(root_module)
    return found


def state_run_resources():
    """Read exact IDs from this run's Terraform state, including a partial apply."""
    document = json.loads(tf("show", "-json", capture=True))
    found = {}

    def visit(module):
        for resource in module.get("resources", []):
            address = resource.get("address", "")
            if address in {
                "module.processing.aws_emr_cluster.congestion",
                "module.kafka.aws_s3_bucket.archive",
            }:
                resource_id = resource.get("values", {}).get("id")
                if resource_id:
                    found[address] = resource_id
        for child in module.get("child_modules", []):
            visit(child)

    root_module = document.get("values", {}).get("root_module")
    if root_module:
        visit(root_module)
    return found


def reviewed_plan():
    target = WORK / "run.tfplan"
    tf("plan", "-input=false", "-no-color", "-var-file=" + str(VARIABLES), "-out=" + str(target))
    document = json.loads(tf("show", "-json", str(target), capture=True))
    changes = document.get("resource_changes", [])
    forbidden = {"aws_db_instance", "aws_nat_gateway", "aws_eks_cluster", "aws_kinesisanalyticsv2_application"}
    unexpected = [r["address"] for r in changes if r["type"] in forbidden and r["change"]["actions"] != ["no-op"]]
    if unexpected:
        raise RuntimeError("Unexpected resources in Phase 4 plan: " + ", ".join(unexpected))
    if any("delete" in r["change"]["actions"] for r in changes):
        raise RuntimeError("Deployment plan would delete or replace a resource")
    summary = [{"address": r["address"], "type": r["type"], "actions": r["change"]["actions"]}
               for r in changes if r["change"]["actions"] != ["no-op"]]
    (WORK / "reviewed-plan.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if not any(r["type"] == "aws_emr_cluster" for r in summary):
        raise RuntimeError("Reviewed plan does not contain the approved EMR managed cluster")
    print(f"Reviewed {len(summary)} changes: EMR present; no RDS, NAT, EKS or former managed Flink", flush=True)
    return target, summary


def wait_cluster(emr, cluster_id, wanted, seconds=1800):
    wanted = set(wanted)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        cluster = emr.describe_cluster(ClusterId=cluster_id)["Cluster"]
        state = cluster["Status"]["State"]
        if state in wanted:
            return cluster
        if state in {"TERMINATED_WITH_ERRORS"}:
            raise RuntimeError("EMR failed: " + json.dumps(cluster["Status"], default=str))
        print("EMR:", state, "waiting for", sorted(wanted), flush=True)
        time.sleep(15)
    raise TimeoutError("EMR did not reach " + "/".join(sorted(wanted)))


def add_step(emr, cluster_id, name, args):
    response = emr.add_job_flow_steps(JobFlowId=cluster_id, Steps=[{
        "Name": name, "ActionOnFailure": "CONTINUE",
        "HadoopJarStep": {"Jar": "command-runner.jar", "Args": args}
    }])
    return response["StepIds"][0]


def wait_step(emr, cluster_id, step_id, seconds=1200):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        step = emr.describe_step(ClusterId=cluster_id, StepId=step_id)["Step"]
        state = step["Status"]["State"]
        if state == "COMPLETED":
            return step
        if state in {"FAILED", "CANCELLED", "INTERRUPTED"}:
            raise RuntimeError("EMR step failed: " + json.dumps(step["Status"], default=str))
        print("EMR step", step_id, state, flush=True)
        time.sleep(10)
    raise TimeoutError("EMR step did not complete: " + step_id)


def submit_job(emr, outputs, project, stage, checkpoint=None):
    if stage not in (1, 2) or (stage == 2) != bool(checkpoint):
        raise ValueError("Stage 2 requires a checkpoint; stage 1 must start without one")
    args = ["flink", "run", "-m", "yarn-cluster", "-d", "-yjm", "1024", "-ytm", "2048"]
    if checkpoint:
        args.extend(["-s", checkpoint])
    args.extend([
        "-c", "com.smarttraffic.FlinkJob",
        f"s3://{outputs['archive_bucket']}/{outputs['artifact_key']}",
        "--KAFKA_BOOTSTRAP_SERVERS", outputs["kafka_bootstrap_servers"],
        "--KAFKA_AUTH_MODE", "iam", "--KAFKA_RAW_TOPIC", "traffic.raw",
        "--KAFKA_RESULTS_TOPIC", "traffic.results", "--KAFKA_GROUP_ID", "congestion-v1",
        "--CHECKPOINT_URI", f"s3://{outputs['archive_bucket']}/checkpoints/{project}",
        "--VERIFICATION_STAGE", str(stage), "--VERIFICATION_RUN_ID", project,
        "--VERIFICATION_BUCKET", outputs["archive_bucket"]
    ])
    step_id = add_step(emr, outputs["emr_cluster_id"], f"phase4-stage-{stage}", args)
    wait_step(emr, outputs["emr_cluster_id"], step_id)
    return step_id


def wait_marker(s3, bucket, project, stage, seconds=900):
    key = f"verification/{project}/stage-{stage}.json"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            result = json.loads(body)
            validate_result(result, project, stage)
            return {"key": key, "result": result}
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404"}:
                raise
        print("Waiting for managed stage", stage, "evidence", flush=True)
        time.sleep(10)
    raise TimeoutError("Managed verification marker missing for stage " + str(stage))


def validate_result(result, project, stage):
    schema = json.loads((ROOT / "contracts/v1/result.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    start = f"2026-11-10T10:0{stage - 1}:00Z"
    end = f"2026-11-10T10:0{stage}:00Z"
    expected = {
        "schema_version": "1.0", "intersection_id": project + "-main",
        "window_start": start, "window_end": end,
        "window_id": f"{project}-main/{start}/{end}/v1",
        "reading_count": 2 if stage == 1 else 3,
        "vehicle_count_sum": 5 if stage == 1 else None,
        "average_speed": 20 if stage == 1 else 40,
        "average_occupancy": 0.6 if stage == 1 else None,
        "congestion": "medium" if stage == 1 else "low",
    }
    if result != expected:
        raise AssertionError("Managed known-output mismatch: " + json.dumps(result))


def wait_checkpoint(s3, bucket, project, seconds=180):
    """Use the checkpoint ID emitted after both pending inputs passed the Flink operator."""
    prefix = f"checkpoints/{project}/"
    marker_key = f"verification/{project}/checkpoint-ready.json"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            marker = json.loads(s3.get_object(Bucket=bucket, Key=marker_key)["Body"].read())
            checkpoint_id = marker["checkpoint_id"]
            if marker["run"] != project or not isinstance(checkpoint_id, int) or checkpoint_id < 1:
                raise AssertionError("Invalid checkpoint receipt")
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if key.startswith(prefix) and key.endswith(f"/chk-{checkpoint_id}/_metadata"):
                        return "s3://" + bucket + "/" + key.removesuffix("/_metadata"), marker
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404"}:
                raise
        time.sleep(5)
    raise TimeoutError("No completed checkpoint found after both pending readings")


def stop_flink(emr, cluster_id):
    # This cluster is created for this run alone. Fail if the job has already disappeared.
    command = "set -eu; ids=$(yarn application -list -appStates RUNNING | awk '$1 ~ /^application_/ {print $1}'); test -n \"$ids\"; for id in $ids; do yarn application -kill \"$id\"; done"
    step_id = add_step(emr, cluster_id, "stop-flink-applications", ["bash", "-c", command])
    wait_step(emr, cluster_id, step_id)
    time.sleep(10)


def empty_versioned_bucket(s3, bucket, account, project):
    if not bucket.startswith(project + "-kafka-"):
        raise RuntimeError("Refusing to empty a bucket outside this exact run")
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, ExpectedBucketOwner=account):
        versions = [{"Key": item["Key"], "VersionId": item["VersionId"]}
                    for field in ("Versions", "DeleteMarkers") for item in page.get(field, [])]
        for start in range(0, len(versions), 1000):
            s3.delete_objects(Bucket=bucket, ExpectedBucketOwner=account,
                              Delete={"Objects": versions[start:start + 1000], "Quiet": True})


def cleanup(session, project, evidence):
    print("TEARDOWN: resolving only resources recorded in this run's Terraform state", flush=True)
    evidence["cleanup_emr_security_groups_from_state"] = state_emr_security_groups()
    owned = state_run_resources()
    evidence["cleanup_run_resources_from_state"] = owned
    cleanup_errors = []
    emr = session.client("emr")
    cluster_id = owned.get("module.processing.aws_emr_cluster.congestion")
    if cluster_id:
        try:
            state = emr.describe_cluster(ClusterId=cluster_id)["Cluster"]["Status"]["State"]
            if state not in {"TERMINATED", "TERMINATED_WITH_ERRORS", "TERMINATING"}:
                emr.set_termination_protection(JobFlowIds=[cluster_id], TerminationProtected=False)
                emr.terminate_job_flows(JobFlowIds=[cluster_id])
            wait_cluster(emr, cluster_id, {"TERMINATED", "TERMINATED_WITH_ERRORS"}, 1800)
        except emr.exceptions.InvalidRequestException:
            pass
        except Exception as exc:
            cleanup_errors.append("EMR termination: " + str(exc))
    bucket = owned.get("module.kafka.aws_s3_bucket.archive")
    if bucket:
        try:
            account = session.client("sts").get_caller_identity()["Account"]
            empty_versioned_bucket(session.client("s3"), bucket, account, project)
        except Exception as exc:
            cleanup_errors.append("S3 emptying: " + str(exc))
    try:
        tf("destroy", "-auto-approve", "-input=false", "-no-color", "-var-file=" + str(VARIABLES), timeout=4200)
    except Exception as exc:
        cleanup_errors.append("Terraform destroy: " + str(exc))
    remaining = tf("state", "list", capture=True).strip()
    evidence["terraform_state_empty_after_teardown"] = not remaining
    if remaining:
        cleanup_errors.append("Resources remain in Terraform state: " + remaining)
    evidence["remaining_emr_clusters"] = [c["Name"] for page in emr.get_paginator("list_clusters").paginate(ClusterStates=["STARTING", "BOOTSTRAPPING", "RUNNING", "WAITING", "TERMINATING"])
                                                for c in page.get("Clusters", []) if c["Name"].startswith(project)]
    evidence["remaining_msk_clusters"] = [c["ClusterName"] for page in session.client("kafka").get_paginator("list_clusters_v2").paginate()
                                                for c in page.get("ClusterInfoList", []) if c["ClusterName"].startswith(project)]
    evidence["remaining_buckets"] = [b["Name"] for b in session.client("s3").list_buckets().get("Buckets", []) if b["Name"].startswith(project)]
    if any(evidence[key] for key in ("remaining_emr_clusters", "remaining_msk_clusters", "remaining_buckets")):
        cleanup_errors.append("Independent AWS cleanup check found run-owned resources")
    if cleanup_errors:
        evidence["cleanup_errors"] = cleanup_errors
        raise RuntimeError("; ".join(cleanup_errors))
    print("PASS teardown: Terraform state empty and no run-owned EMR/MSK/S3 resources", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true")
    parser.add_argument("--reuse-reviewed-run", action="store_true",
                        help="Reuse the disabled run ID from matching plan-only evidence; replan before apply")
    args = parser.parse_args()
    if args.reuse_reviewed_run and (args.plan_only or args.cleanup_only):
        parser.error("--reuse-reviewed-run is only for a later authorized execution")
    WORK.mkdir(parents=True, exist_ok=True)
    existing = json.loads(VARIABLES.read_text(encoding="utf-8")) if VARIABLES.exists() else {}
    if args.reuse_reviewed_run and existing.get("deployment_approved", False):
        raise RuntimeError("Reviewed run reuse requires the deployment guard to be disabled")
    if not args.cleanup_only and not existing.get("deployment_approved", False):
        reviewed = json.loads(PLAN_EVIDENCE.read_text(encoding="utf-8")) if args.reuse_reviewed_run and PLAN_EVIDENCE.exists() else {}
        existing = choose_run_variables(existing, args.reuse_reviewed_run, reviewed)
        VARIABLES.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    elif args.cleanup_only and not VARIABLES.exists():
        raise RuntimeError("Cleanup requested but no run variables exist")
    project = existing["project_name"]
    evidence = {
        "run_name": project, "scope": "temporary AWS EMR Phase 4 verification",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "managed_verified": False, "teardown_requested": True
    }
    error = None
    session = None
    try:
        session = boto3.Session(profile_name=PROFILE, region_name=REGION)
        identity = session.client("sts").get_caller_identity()
        evidence.update({"account": identity["Account"], "principal_arn": identity["Arn"]})
        tf("init", "-backend=false", "-input=false", "-no-color")
        if args.cleanup_only:
            cleanup(session, project, evidence)
            return
        plan_file, summary = reviewed_plan()
        evidence["reviewed_plan"] = summary
        if args.plan_only:
            print("PLAN ONLY: no AWS resources created", flush=True)
            return
        evidence["kafka_service_role_before"] = kafka_service_role_before(session)
        print("PROVISIONING temporary EMR/MSK stack:", project, flush=True)
        tf("apply", "-input=false", "-no-color", str(plan_file))
        outputs = state_outputs()
        evidence["outputs"] = outputs
        emr, s3 = session.client("emr"), session.client("s3")
        cluster = wait_cluster(emr, outputs["emr_cluster_id"], {"WAITING", "RUNNING"})
        evidence["emr_release_label"] = cluster["ReleaseLabel"]
        evidence["emr_instance_collection_type"] = cluster["InstanceCollectionType"]
        evidence["stage1_step"] = submit_job(emr, outputs, project, 1)
        evidence["stage1_actual_result"] = wait_marker(s3, outputs["archive_bucket"], project, 1)
        print("PASS managed stage 1 known input/output", flush=True)
        checkpoint, receipt = wait_checkpoint(s3, outputs["archive_bucket"], project)
        evidence["checkpoint_receipt"] = receipt
        evidence["restore_checkpoint"] = checkpoint
        stop_flink(emr, outputs["emr_cluster_id"])
        evidence["stage2_step"] = submit_job(emr, outputs, project, 2, checkpoint)
        evidence["stage2_actual_result"] = wait_marker(s3, outputs["archive_bucket"], project, 2)
        evidence["managed_verified"] = True
        print("PASS managed checkpoint restore, pending aggregation and duplicate suppression", flush=True)
    except BaseException as exc:
        evidence["failure"] = str(exc)
        traceback.print_exc()
        error = exc
    finally:
        if session is not None and not args.plan_only and not args.cleanup_only:
            try:
                cleanup(session, project, evidence)
            except BaseException as exc:
                evidence["cleanup_failure"] = str(exc)
                traceback.print_exc()
                error = error or exc
        evidence["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        evidence_path = PLAN_EVIDENCE if args.plan_only else EVIDENCE
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8")
        if VARIABLES.exists() and (not error or args.plan_only or evidence.get("terraform_state_empty_after_teardown")):
            disabled = {**json.loads(VARIABLES.read_text(encoding="utf-8")), "deployment_approved": False}
            VARIABLES.write_text(json.dumps(disabled, indent=2) + "\n", encoding="utf-8")
    if error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
