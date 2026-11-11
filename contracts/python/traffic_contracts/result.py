"""Shared validation of the approved v1 Flink result contract."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Mapping

FIELDS = frozenset({
    "schema_version", "window_id", "intersection_id", "window_start", "window_end",
    "reading_count", "vehicle_count_sum", "average_speed", "average_occupancy",
    "congestion",
})
LEVELS = frozenset({"low", "medium", "high", "unknown"})


def _decimal(value: object, name: str, maximum: Decimal | None = None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be a number or null")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{name} must be finite")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not number.is_finite() or number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f"{name} is out of range")
    return number


def _minute(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name} must be a UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if parsed.tzinfo != timezone.utc or parsed.second or parsed.microsecond:
        raise ValueError(f"{name} must be an exact UTC minute")
    if value != parsed.strftime("%Y-%m-%dT%H:%M:00Z"):
        raise ValueError(f"{name} must use canonical UTC minute format")
    return parsed


def validate_result(result: Mapping[str, object]) -> dict:
    """Return a detached, validated v1 result; reject inconsistent Flink outputs."""
    if not isinstance(result, Mapping) or set(result) != FIELDS:
        raise ValueError("result fields do not match the v1 contract")
    data = dict(result)
    if data["schema_version"] != "1.0":
        raise ValueError("unsupported result schema version")
    intersection = data["intersection_id"]
    if (not isinstance(intersection, str) or not intersection.strip()
            or len(intersection) > 128):
        raise ValueError("intersection_id is invalid")
    start = _minute(data["window_start"], "window_start")
    end = _minute(data["window_end"], "window_end")
    if end - start != timedelta(minutes=1):
        raise ValueError("result must describe one 60-second window")
    expected_id = f"{intersection}/{data['window_start']}/{data['window_end']}/v1"
    if data["window_id"] != expected_id or len(expected_id) > 256:
        raise ValueError("window_id does not match the window")
    count = data["reading_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("reading_count must be a positive integer")
    vehicle_count = data["vehicle_count_sum"]
    if vehicle_count is not None and (isinstance(vehicle_count, bool)
                                      or not isinstance(vehicle_count, int)
                                      or vehicle_count < 0):
        raise ValueError("vehicle_count_sum must be a nonnegative integer or null")
    speed = _decimal(data["average_speed"], "average_speed")
    occupancy = _decimal(data["average_occupancy"], "average_occupancy", Decimal("1"))
    level = data["congestion"]
    if not isinstance(level, str) or level not in LEVELS:
        raise ValueError("invalid congestion level")
    expected_level = "unknown"
    if speed is not None or occupancy is not None:
        if ((speed is not None and speed < 20)
                or (occupancy is not None and occupancy >= Decimal("0.80"))):
            expected_level = "high"
        elif ((speed is not None and speed < 40)
              or (occupancy is not None and occupancy >= Decimal("0.50"))):
            expected_level = "medium"
        else:
            expected_level = "low"
    if level != expected_level:
        raise ValueError("congestion does not match the result measurements")
    return data
