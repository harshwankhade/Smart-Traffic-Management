"""Traffic Analytics-owned persistence for publisher recovery events."""
import os
from typing import Mapping

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from traffic_contracts.dynamo_store import _to_dynamo, resource_from_environment
from traffic_contracts.recovery import validate_recovery_event


class RecoveryConflict(ValueError):
    pass


class RecoveryRepository:
    def __init__(self, *, resource=None, table_name=None):
        self.table = (resource or resource_from_environment()).Table(
            table_name or os.getenv("RECOVERY_EVENTS_TABLE", "traffic_recovery_events"))

    def ready(self):
        self.table.meta.client.describe_table(TableName=self.table.name)

    def put(self, event: Mapping[str, object]) -> str:
        payload = _to_dynamo(validate_recovery_event(event))
        item = {"publisher_id": payload["publisher_id"],
                "recovery_key": f"{payload['occurred_at']}#{payload['recovery_id']}", "payload": payload}
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(publisher_id)")
            return "created"
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        previous = self.table.get_item(Key={"publisher_id": item["publisher_id"],
                                            "recovery_key": item["recovery_key"]}, ConsistentRead=True).get("Item")
        if previous is None:
            raise RuntimeError("conditional recovery write failed but record is unavailable; retry")
        if previous.get("payload") != payload:
            raise RecoveryConflict("recovery event identity already has different content")
        return "unchanged"

    def get(self, publisher_id, recovery_id):
        response = self.table.query(KeyConditionExpression=Key("publisher_id").eq(publisher_id), ConsistentRead=True)
        for item in response.get("Items", []):
            if item["payload"].get("recovery_id") == recovery_id:
                return item["payload"]
        return None

    def query(self, publisher_id, *, from_time=None, to_time=None, limit=50, exclusive_start_key=None):
        if not isinstance(publisher_id, str) or not publisher_id.strip():
            raise ValueError("publisher_id is required")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        # Keys append '#<recovery_id>'; using the bare upper timestamp excludes that instant.
        low, high = f"{from_time}#" if from_time else "0", to_time if to_time else "\uffff"
        request = {"KeyConditionExpression": Key("publisher_id").eq(publisher_id) & Key("recovery_key").between(low, high),
                   "Limit": limit, "ConsistentRead": True, "ScanIndexForward": True}
        if exclusive_start_key:
            if set(exclusive_start_key) != {"publisher_id", "recovery_key"} or exclusive_start_key["publisher_id"] != publisher_id:
                raise ValueError("pagination key does not belong to the publisher")
            request["ExclusiveStartKey"] = exclusive_start_key
        response = self.table.query(**request)
        return [item["payload"] for item in response.get("Items", [])], response.get("LastEvaluatedKey")
