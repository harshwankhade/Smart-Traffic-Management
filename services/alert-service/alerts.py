"""Validate v1 queue requests and store one logical alert per stable alert ID."""

import os
import re
from datetime import UTC, datetime

from botocore.exceptions import ClientError
from traffic_contracts.dynamo_store import resource_from_environment

UTC_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
FIELDS = {"schema_version", "alert_id", "source_type", "source_id",
          "intersection_id", "reason", "occurred_at", "rule_version"}
INCIDENT_REASON = re.compile(r"incident_(collision|closure|disruption)_(open|resolved)\Z")


class AlertConflict(Exception):
    """An alert ID was reused with different request content."""


def validate_request(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("alert request has unexpected or missing fields")
    if value["schema_version"] != "1.0" or value["rule_version"] != "1":
        raise ValueError("unsupported alert version")
    for field, maximum in (("alert_id", 256), ("source_id", 256),
                           ("intersection_id", 128), ("reason", 2000)):
        text = value[field]
        if not isinstance(text, str) or not text.strip() or len(text) > maximum:
            raise ValueError(f"invalid {field}")
    stamp = value["occurred_at"]
    if not isinstance(stamp, str) or not UTC_TIME.fullmatch(stamp):
        raise ValueError("occurred_at must be UTC RFC3339 Z")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid occurred_at") from exc
    source = value["source_id"]
    if value["source_type"] == "congestion":
        window_parts = source[len(value["intersection_id"]) + 1:].split("/")
        if (value["alert_id"] != source + "/congestion-alert/v1"
                or value["reason"] != "high_congestion"
                or not source.startswith(value["intersection_id"] + "/")
                or len(window_parts) != 3 or window_parts[-1] != "v1"
                or not UTC_TIME.fullmatch(window_parts[0])
                or not UTC_TIME.fullmatch(window_parts[1])
                or stamp != window_parts[1]):
            raise ValueError("invalid congestion identity")
    elif value["source_type"] == "incident":
        if (value["alert_id"] != source + "/incident-alert/v1"
                or not INCIDENT_REASON.fullmatch(value["reason"])):
            raise ValueError("invalid incident identity")
    else:
        raise ValueError("invalid alert source_type")
    return dict(value)


class AlertRepository:
    def __init__(self, *, resource=None, table_name=None):
        name = table_name or os.getenv("ALERTS_TABLE", "traffic_alerts")
        if not isinstance(name, str) or not name:
            raise ValueError("alert table name is required")
        self.table = (resource or resource_from_environment()).Table(name)

    def put(self, request):
        validated = validate_request(request)
        item = {**validated, "outcome": "recorded",
                "processed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(alert_id)")
            return "created"
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        previous = self.get(validated["alert_id"])
        if previous is None:
            raise RuntimeError("conditional alert write failed but record is unavailable")
        if any(previous.get(key) != validated[key] for key in FIELDS):
            raise AlertConflict("alert identity conflicts with stored request")
        return "unchanged"

    def get(self, alert_id):
        return self.table.get_item(Key={"alert_id": alert_id}, ConsistentRead=True).get("Item")
