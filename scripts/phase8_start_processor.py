"""Render an EMR Flink step offline; submit only with --submit and explicit approval.

Input: `terraform output -json` from phase8, saved to an ignored local file.
Wait for Kafka DNS/topic readiness and EMR WAITING before submitting. No apply,
Git operation, public request, or teardown is performed by this helper.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex

CHECKPOINT_FILES_QUERY = "not_null(Contents, `[]`)[?ends_with(Key, '/') == `false`].Key"


def step(outputs, restore_checkpoint=None):
    def value(name):
        item = outputs[name]
        return item["value"] if isinstance(item, dict) and "value" in item else item

    jar = value("flink_artifact_uri")
    ca = value("kafka_ca_uri")
    brokers = value("kafka_bootstrap_servers")
    bucket = value("archive_bucket")
    if not jar.startswith("s3://") or not ca.startswith("s3://") or brokers != "kafka.smarttraffic.internal:9093":
        raise ValueError("Expected the private TLS Kafka runtime outputs")
    command = ["flink", "run", "-m", "yarn-cluster", "-p", "1", "-yjm", "1024", "-ytm", "2048"]
    if restore_checkpoint:
        if not restore_checkpoint.startswith(f"s3://{bucket}/checkpoints/"):
            raise ValueError("Restore checkpoint must belong to this runtime bucket")
        command += ["-s", restore_checkpoint]
    command += ["-c", "com.smarttraffic.FlinkJob",
               '"$work/processor.jar"', "--KAFKA_BOOTSTRAP_SERVERS", brokers,
               "--KAFKA_AUTH_MODE", "tls", "--KAFKA_SSL_CA_LOCATION", '"$work/kafka-ca.pem"',
               "--CHECKPOINT_URI", f"s3://{bucket}/checkpoints/demo"]
    # Values from outputs are shell-quoted; only these two fixed local paths expand.
    rendered = " ".join(arg if arg.startswith('"$work/') else shlex.quote(arg) for arg in command)
    script = "\n".join([
        "set -euo pipefail",
        'work=$(mktemp -d /tmp/smarttraffic-flink.XXXXXX)',
        'exec > >(tee "$work/launch.log") 2>&1',
        f"log_uri={shlex.quote('s3://' + bucket + '/emr-logs/processor-live.log')}",
        '( while sleep 15; do aws s3 cp "$work/launch.log" "$log_uri" --only-show-errors || true; done ) &',
        'uploader=$!',
        'trap \'result=$?; kill "$uploader" 2>/dev/null || true; aws s3 cp "$work/launch.log" "$log_uri" --only-show-errors || true; rm -f -- "$work/processor.jar" "$work/kafka-ca.pem" "$work/launch.log"; rmdir -- "$work"; exit "$result"\' EXIT',
        "applications=$(yarn application -list -appTypes FLINK -appStates RUNNING,ACCEPTED)",
        "if grep -q '^application_' <<< \"$applications\"; then echo 'An existing Flink application must be reconciled first' >&2; exit 1; fi",
        *([] if restore_checkpoint else [
            f"checkpoints=$(aws s3api list-objects-v2 --bucket {shlex.quote(bucket)} --prefix checkpoints/demo/ --query {shlex.quote(CHECKPOINT_FILES_QUERY)} --output text)",
            'if [[ -n "$checkpoints" && "$checkpoints" != "None" ]]; then echo "Existing checkpoints require --restore-checkpoint; refusing an implicit state rebuild" >&2; exit 1; fi',
        ]),
        f'aws s3 cp {shlex.quote(jar)} "$work/processor.jar"',
        f'aws s3 cp {shlex.quote(ca)} "$work/kafka-ca.pem"',
        rendered,
    ])
    return {"Name": "smarttraffic-demo-flink", "ActionOnFailure": "CONTINUE",
            "HadoopJarStep": {"Jar": "command-runner.jar", "Args": ["bash", "-c", script]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-json", required=True)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--restore-checkpoint", help="Explicit completed S3 checkpoint for recovery, not a state rebuild.")
    args = parser.parse_args()
    outputs = json.loads(Path(args.outputs_json).read_text(encoding="utf-8-sig"))
    payload = step(outputs, args.restore_checkpoint)
    if not args.submit:
        print(json.dumps(payload, indent=2))
        return
    if os.getenv("PHASE8_PROCESSOR_START_APPROVED") != "yes":
        parser.error("--submit requires PHASE8_PROCESSOR_START_APPROVED=yes after runtime review")
    import boto3
    emr = boto3.Session(profile_name=os.getenv("AWS_PROFILE"),
                        region_name=os.getenv("AWS_REGION", "ap-south-1")).client("emr")
    cluster = outputs["emr_cluster_id"]
    cluster = cluster["value"] if isinstance(cluster, dict) else cluster
    if emr.describe_cluster(ClusterId=cluster)["Cluster"]["Status"]["State"] != "WAITING":
        raise RuntimeError("EMR must be WAITING before starting the processor")
    # Also prevent queuing a second step while a previous foreground job is active.
    if emr.list_steps(ClusterId=cluster, StepStates=["PENDING", "RUNNING"])["Steps"]:
        raise RuntimeError("Reconcile existing pending/running EMR steps first")
    print(json.dumps(emr.add_job_flow_steps(JobFlowId=cluster, Steps=[payload])["StepIds"]))


if __name__ == "__main__":
    main()
