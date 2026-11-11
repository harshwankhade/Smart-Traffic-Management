"""Stable Phase 6 alert requests and an injectable SQS sender."""

import json
import os
from datetime import UTC

import boto3
from botocore.config import Config


def canonical_body(request):
    return json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def congestion_request(result):
    if result["congestion"] != "high":
        return None
    window = result["window_id"]
    return {"schema_version": "1.0", "alert_id": window + "/congestion-alert/v1",
            "source_type": "congestion", "source_id": window,
            "intersection_id": result["intersection_id"], "reason": "high_congestion",
            "occurred_at": result["window_end"], "rule_version": "1"}


def incident_request(row):
    timestamp = row.updated_at
    if timestamp.tzinfo is None:  # SQLite stores UTC without timezone metadata.
        timestamp = timestamp.replace(tzinfo=UTC)
    return {"schema_version": "1.0", "alert_id": row.event_id + "/incident-alert/v1",
            "source_type": "incident", "source_id": row.event_id,
            "intersection_id": row.intersection_id,
            "reason": f"incident_{row.type}_{row.status}",
            "occurred_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "rule_version": "1"}


class SqsAlertSender:
    def __init__(self, *, client=None, queue_url=None):
        self.queue_url = queue_url or os.getenv("ALERT_QUEUE_URL")
        if not self.queue_url:
            raise ValueError("ALERT_QUEUE_URL is required when alert delivery is enabled")
        self.client = client or boto3.client(
            "sqs", region_name=os.getenv("AWS_REGION", "ap-south-1"),
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 2}))

    def send(self, request):
        response = self.client.send_message(QueueUrl=self.queue_url,
                                            MessageBody=canonical_body(request))
        if not response.get("MessageId"):
            raise RuntimeError("SQS did not acknowledge the alert request")
        return response["MessageId"]


class InMemoryAlertSender:
    """Local controllable sender; records accepted bodies and can simulate outage."""

    def __init__(self):
        self.messages = []
        self.available = True

    def send(self, request):
        if not self.available:
            raise ConnectionError("local alert queue unavailable")
        self.messages.append(canonical_body(request))
        return str(len(self.messages))
