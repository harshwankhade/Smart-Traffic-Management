"""Validation and deterministic identity for ZooKeeper publisher recovery events."""
from datetime import datetime, timezone
from typing import Mapping

EVENT_TYPES = frozenset({"leader_elected", "leader_lost", "session_suspended", "session_lost", "session_rejoined"})
FIELDS = frozenset({"schema_version", "recovery_id", "publisher_id", "session_id", "event_type", "occurred_at", "leader"})


def recovery_id(publisher_id: str, session_id: str, event_type: str) -> str:
    return f"{publisher_id}/{session_id}/{event_type}/v1"


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("occurred_at must be a UTC RFC3339 Z timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("occurred_at is invalid") from error
    if parsed.tzinfo != timezone.utc or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("occurred_at must be UTC")
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if value != canonical:
        raise ValueError("occurred_at must use canonical microsecond UTC format")
    return canonical


def validate_recovery_event(event: Mapping[str, object]) -> dict:
    if not isinstance(event, Mapping) or set(event) != FIELDS:
        raise ValueError("recovery event fields do not match the v1 contract")
    data = dict(event)
    if data["schema_version"] != "1.0":
        raise ValueError("unsupported recovery event schema version")
    for field, maximum in (("publisher_id", 128), ("session_id", 128)):
        value = data[field]
        if not isinstance(value, str) or not value.strip() or "/" in value or len(value) > maximum:
            raise ValueError(f"{field} is invalid")
    if data["event_type"] not in EVENT_TYPES:
        raise ValueError("event_type is invalid")
    if type(data["leader"]) is not bool:
        raise ValueError("leader must be a boolean")
    data["occurred_at"] = _timestamp(data["occurred_at"])
    expected = recovery_id(data["publisher_id"], data["session_id"], data["event_type"])
    if data["recovery_id"] != expected or len(expected) > 384:
        raise ValueError("recovery_id does not match the event identity")
    return data
