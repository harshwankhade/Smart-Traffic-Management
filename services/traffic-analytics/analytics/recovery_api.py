import base64
import json

from traffic_contracts.recovery import validate_recovery_event


def _cursor(publisher_id, from_time, to_time, limit, key=None):
    if key is None:
        return None
    raw = json.dumps({"v": 1, "publisher_id": publisher_id, "from": from_time, "to": to_time,
                      "limit": limit, "key": key}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(token, publisher_id, from_time, to_time, limit):
    try:
        value = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except Exception as error:
        raise ValueError("cursor is malformed") from error
    if (not isinstance(value, dict) or value.get("v") != 1 or value.get("publisher_id") != publisher_id
            or value.get("from") != from_time or value.get("to") != to_time or value.get("limit") != limit
            or set(value.get("key", {})) != {"publisher_id", "recovery_key"}):
        raise ValueError("cursor does not match this query")
    return value["key"]


def page(repository, publisher_id, from_time=None, to_time=None, limit=50, cursor=None):
    if not isinstance(publisher_id, str) or not publisher_id.strip() or len(publisher_id) > 128:
        raise ValueError("publisher_id is invalid")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    for value in (from_time, to_time):
        if value is not None:
            validate_recovery_event({"schema_version": "1.0", "publisher_id": publisher_id,
                                     "session_id": "validation", "event_type": "leader_lost",
                                     "recovery_id": f"{publisher_id}/validation/leader_lost/v1",
                                     "occurred_at": value, "leader": False})
    if from_time and to_time and from_time >= to_time:
        raise ValueError("from must be before to")
    key = _decode(cursor, publisher_id, from_time, to_time, limit) if cursor else None
    items, next_key = repository.query(publisher_id, from_time=from_time, to_time=to_time,
                                       limit=limit, exclusive_start_key=key)
    return {"items": items, "next_cursor": _cursor(publisher_id, from_time, to_time, limit, next_key)}
