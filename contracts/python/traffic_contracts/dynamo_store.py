"""Small DynamoDB adapter for independently owned Phase 5 window tables."""

import os
import re
from decimal import Decimal
from typing import Mapping

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError

MINUTE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z\Z")
SERIALIZER = TypeSerializer()


class RecordConflict(ValueError):
    """A stable window identity was reused with different content."""


def resource_from_environment():
    """Use local-only dummy credentials for an explicit loopback endpoint."""
    endpoint = os.getenv("DYNAMODB_ENDPOINT_URL")
    options = {"region_name": os.getenv("AWS_REGION", "ap-south-1"),
               "config": Config(connect_timeout=2, read_timeout=3,
                                retries={"max_attempts": 2}, proxies={})}
    if endpoint:
        if endpoint not in ("http://127.0.0.1:8000", "http://localhost:8000"):
            raise ValueError("DYNAMODB_ENDPOINT_URL must be the approved local loopback endpoint")
        options.update(endpoint_url=endpoint, aws_access_key_id="local",
                       aws_secret_access_key="local")
    return boto3.resource("dynamodb", **options)


def window_start_from_id(intersection_id: str, window_id: str) -> str:
    if not isinstance(intersection_id, str) or not intersection_id.strip():
        raise ValueError("intersection_id is required")
    prefix = intersection_id + "/"
    if not isinstance(window_id, str) or not window_id.startswith(prefix):
        raise ValueError("window_id does not belong to intersection_id")
    start = window_id[len(prefix):].split("/", 1)[0]
    if not MINUTE.fullmatch(start):
        raise ValueError("window_id has no canonical window_start")
    return start


def _to_dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return {key: _to_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(item) for item in value]
    return value


class WindowStore:
    """A table-specific repository; no cross-table reads, writes or scans."""

    def __init__(self, table_name: str, *, resource=None):
        if not table_name or not isinstance(table_name, str):
            raise ValueError("table name is required")
        self.table = (resource or resource_from_environment()).Table(table_name)

    def ready(self):
        """Check the owned table through a live DynamoDB request."""
        self.table.meta.client.describe_table(TableName=self.table.name)

    def put(self, record: Mapping[str, object]) -> str:
        if not isinstance(record, Mapping):
            raise ValueError("record must be a mapping")
        intersection = record.get("intersection_id")
        window_id = record.get("window_id")
        start = window_start_from_id(intersection, window_id)
        if record.get("window_start") != start:
            raise ValueError("window_start does not match window_id")
        payload = _to_dynamo(dict(record))
        item = {"intersection_id": intersection,
                "window_key": f"{start}#{window_id}", "payload": payload}
        # Check number precision/range locally, before making any network request.
        try:
            SERIALIZER.serialize(item)
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError("record contains a value DynamoDB cannot store") from exc
        try:
            self.table.put_item(Item=item,
                                ConditionExpression="attribute_not_exists(intersection_id)")
            return "created"
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        previous = self.table.get_item(Key={"intersection_id": intersection,
                                            "window_key": item["window_key"]},
                                       ConsistentRead=True).get("Item")
        if previous is None:
            raise RuntimeError("conditional write failed but record is unavailable; retry")
        if previous.get("payload") != payload:
            raise RecordConflict(f"window {window_id} already has different content")
        return "unchanged"

    def get(self, intersection_id: str, window_id: str):
        start = window_start_from_id(intersection_id, window_id)
        item = self.table.get_item(
            Key={"intersection_id": intersection_id,
                 "window_key": f"{start}#{window_id}"},
            ConsistentRead=True).get("Item")
        return item["payload"] if item else None

    def query(self, intersection_id: str, *, from_start: str | None = None,
              to_start: str | None = None, limit: int = 50,
              exclusive_start_key: dict | None = None):
        if not isinstance(intersection_id, str) or not intersection_id.strip():
            raise ValueError("intersection_id is required")
        for value in (from_start, to_start):
            if value is not None and (not isinstance(value, str) or not MINUTE.fullmatch(value)):
                raise ValueError("time bounds must be canonical UTC minute timestamps")
        if from_start and to_start and from_start >= to_start:
            raise ValueError("from_start must be before to_start")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        low = f"{from_start}#" if from_start else "0"
        high = f"{to_start}#" if to_start else "\uffff"
        request = {"KeyConditionExpression": Key("intersection_id").eq(intersection_id)
                   & Key("window_key").between(low, high),
                   "Limit": limit, "ConsistentRead": True, "ScanIndexForward": True}
        if exclusive_start_key:
            if (set(exclusive_start_key) != {"intersection_id", "window_key"}
                    or exclusive_start_key["intersection_id"] != intersection_id):
                raise ValueError("pagination key does not belong to the query intersection")
            request["ExclusiveStartKey"] = exclusive_start_key
        response = self.table.query(**request)
        return [item["payload"] for item in response.get("Items", [])], response.get("LastEvaluatedKey")
