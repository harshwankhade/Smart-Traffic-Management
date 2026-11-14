"""Phase 8 cloud acceptance workflow, deliberately locked until a cloud run is authorized."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from uuid import uuid4


REQUIRED_FOR_CLOUD = ("PHASE8_PUBLIC_URL", "PHASE8_ARCHIVE_BUCKET", "PHASE8_RECOMMENDATIONS_TABLE",
                      "PHASE8_SUMMARIES_TABLE", "PHASE8_ALERTS_TABLE", "PHASE8_ALERT_QUEUE_URL",
                      "PHASE8_LAMBDA_NAME", "PHASE8_EMR_CLUSTER_ID")


def check_only() -> None:
    print(json.dumps({
        "mode": "static-only",
        "cloud_run_locked": True,
        "required_for_cloud": REQUIRED_FOR_CLOUD,
        "workflow": [
            "Argo Application synced and all six Pods ready",
            "public REST creates an intersection, sensor, reading and incident",
            "ingestion REST invokes private Publisher gRPC; Kafka input produces EMR/Flink results",
            "public analytics and recommendation APIs return the resulting window",
            "S3 archive, DynamoDB tables, SQS/Lambda alert and EMR cluster are queried read-only",
            "ZooKeeper leader is deleted through a Git revision / rollout and takeover is observed",
            "remove the Git-tracked root Application, wait for prune, then follow Terraform teardown/audit",
        ],
    }, indent=2))


def cloud_run() -> None:
    missing = [name for name in REQUIRED_FOR_CLOUD if not os.getenv(name)]
    if missing:
        raise RuntimeError("missing cloud-run inputs: " + ", ".join(missing))
    import boto3
    import httpx

    prefix = f"phase8-{uuid4().hex[:10]}"
    base = os.environ["PHASE8_PUBLIC_URL"].rstrip("/")
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    intersection = f"{prefix}-intersection"
    sensor = f"{prefix}-sensor"
    event = f"{prefix}-reading"
    client = httpx.Client(timeout=15, follow_redirects=False)
    try:
        responses = [
            client.post(base + "/intersections", json={"intersection_id": intersection, "name": "Phase 8 demo", "location": "synthetic"}),
            client.post(base + "/sensors", json={"sensor_id": sensor, "intersection_id": intersection, "sensor_type": "camera"}),
            client.post(base + "/readings", json={"event_id": event, "sensor_id": sensor, "observed_at": timestamp, "vehicle_count": 100, "average_speed_kph": 8.0, "occupancy": 0.95}),
        ]
        for response in responses:
            if response.status_code not in (201, 202):
                raise RuntimeError(f"public REST failed: {response.status_code} {response.text}")
        deadline = time.monotonic() + 180
        summary = recommendation = None
        while time.monotonic() < deadline:
            summary_response = client.get(base + "/traffic/summaries", params={"intersection_id": intersection})
            recommendation_response = client.get(base + "/recommendations", params={"intersection_id": intersection})
            if summary_response.status_code == 200 and recommendation_response.status_code == 200:
                summary, recommendation = summary_response.json(), recommendation_response.json()
                if summary.get("items") and recommendation.get("items"):
                    break
            time.sleep(5)
        if not summary or not summary.get("items") or not recommendation or not recommendation.get("items"):
            raise RuntimeError("Flink result, recommendation, or analytics did not arrive within 180 seconds")
        incident_response = client.post(base + "/incidents", json={"incident_id": f"{prefix}-incident", "intersection_id": intersection, "kind": "collision", "status": "open", "reported_at": timestamp})
        if incident_response.status_code != 201:
            raise RuntimeError(f"incident REST failed: {incident_response.status_code} {incident_response.text}")
    finally:
        client.close()
    session = boto3.Session(profile_name=os.getenv("AWS_PROFILE"), region_name="ap-south-1")
    s3 = session.client("s3")
    dynamodb = session.client("dynamodb")
    sqs = session.client("sqs")
    emr = session.client("emr")
    lamb = session.client("lambda")
    s3.head_bucket(Bucket=os.environ["PHASE8_ARCHIVE_BUCKET"])
    for table in ("PHASE8_RECOMMENDATIONS_TABLE", "PHASE8_SUMMARIES_TABLE", "PHASE8_ALERTS_TABLE"):
        dynamodb.describe_table(TableName=os.environ[table])
    sqs.get_queue_attributes(QueueUrl=os.environ["PHASE8_ALERT_QUEUE_URL"], AttributeNames=["All"])
    lamb.get_function(FunctionName=os.environ["PHASE8_LAMBDA_NAME"])
    emr.describe_cluster(ClusterId=os.environ["PHASE8_EMR_CLUSTER_ID"])
    print(json.dumps({"status": "PASS", "run_prefix": prefix, "event_id": event,
                      "summary": summary["items"][0], "recommendation": recommendation["items"][0]}, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-run", action="store_true", help="exercise the live system after explicit authorization")
    parser.add_argument("--allow-cloud-run", action="store_true", help="required safety acknowledgement with --cloud-run")
    args = parser.parse_args()
    if not args.cloud_run:
        check_only()
        return
    if not args.allow_cloud_run:
        parser.error("--cloud-run requires --allow-cloud-run; do not use before separate authorization")
    cloud_run()


if __name__ == "__main__":
    main()
