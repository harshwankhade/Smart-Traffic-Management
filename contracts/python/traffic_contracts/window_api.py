"""Read-only window API helpers shared by the two Phase 5 services."""

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Response

UTC_INSTANT = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}):(\d{2})(\.\d+)?Z$")
CURSOR_TEXT = re.compile(r"^[A-Za-z0-9_-]{1,4096}$")


def _json(value):
    """Write Decimal as an exact JSON number, including large integer sums."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite stored number")
        return format(value, "f")
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _json(item)
                              for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def json_response(value):
    return Response(content=_json(value), media_type="application/json")


def _instant(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("time bound must be a UTC RFC3339 Z timestamp")
    match = UTC_INSTANT.fullmatch(value)
    if not match:
        raise ValueError("time bound must be a UTC RFC3339 Z timestamp")
    base, seconds, fraction = match.groups()
    try:
        instant = datetime.fromisoformat(f"{base}:{seconds}+00:00")
    except ValueError as exc:
        raise ValueError("time bound is invalid") from exc
    if instant.tzinfo != timezone.utc:
        raise ValueError("time bound must be UTC")
    fractional = Decimal(fraction or "0")
    minute = instant.replace(second=0, microsecond=0)
    try:
        ceil = minute + (timedelta(minutes=1) if instant.second or fractional else timedelta())
    except OverflowError as exc:
        raise ValueError("time bound is out of range") from exc
    return (instant, fractional), ceil.strftime("%Y-%m-%dT%H:%M:00Z")


def _encode_cursor(scope, intersection_id, from_time, to_time, limit, key):
    payload = {"v": 1, "scope": scope, "intersection_id": intersection_id,
               "from": from_time, "to": to_time, "limit": limit, "key": key}
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(token, scope, intersection_id, from_time, to_time, limit):
    if not isinstance(token, str) or not CURSOR_TEXT.fullmatch(token):
        raise ValueError("cursor is malformed")
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("cursor is malformed") from exc
    if not isinstance(data, dict) or set(data) != {"v", "scope", "intersection_id", "from", "to", "limit", "key"}:
        raise ValueError("cursor is malformed")
    if (type(data["v"]) is not int or data["v"] != 1 or data["scope"] != scope
            or data["intersection_id"] != intersection_id or data["from"] != from_time
            or data["to"] != to_time or type(data["limit"]) is not int or data["limit"] != limit):
        raise ValueError("cursor does not match this query")
    key = data["key"]
    if (not isinstance(key, dict) or set(key) != {"intersection_id", "window_key"}
            or key["intersection_id"] != intersection_id
            or not isinstance(key["window_key"], str) or not key["window_key"]):
        raise ValueError("cursor key is invalid")
    return key


def query_page(repository, scope, intersection_id, from_time=None, to_time=None,
               limit=50, cursor=None):
    if not isinstance(intersection_id, str) or not intersection_id.strip() or len(intersection_id) > 128:
        raise ValueError("intersection_id is invalid")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    lower = _instant(from_time)
    upper = _instant(to_time)
    if lower and upper and lower[0] >= upper[0]:
        raise ValueError("from must be before to")
    from_start = lower[1] if lower else None
    to_start = upper[1] if upper else None
    key = (_decode_cursor(cursor, scope, intersection_id, from_time, to_time, limit)
           if cursor is not None else None)
    if key and ((from_start and key["window_key"] < f"{from_start}#")
                or (to_start and key["window_key"] >= f"{to_start}#")):
        raise ValueError("cursor is outside this time range")
    if from_start and to_start and from_start >= to_start:
        return {"items": [], "next_cursor": None}
    items, next_key = repository.query(intersection_id, from_start=from_start,
                                       to_start=to_start, limit=limit,
                                       exclusive_start_key=key)
    next_cursor = (_encode_cursor(scope, intersection_id, from_time, to_time, limit, next_key)
                   if next_key else None)
    return {"items": items, "next_cursor": next_cursor}
