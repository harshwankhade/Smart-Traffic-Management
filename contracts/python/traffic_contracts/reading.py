"""Shared v1 wire validation/normalization, independent of service logic."""
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Reading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=128)
    sensor_id: str = Field(min_length=1, max_length=128)
    intersection_id: str = Field(min_length=1, max_length=128)
    observed_at: str
    vehicle_count: int | None = Field(default=None, ge=0, le=9223372036854775807, strict=True)
    average_speed: float | None = Field(default=None, ge=0, strict=True)
    occupancy: float | None = Field(default=None, ge=0, le=1, strict=True)

    @field_validator("event_id", "sensor_id", "intersection_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("ID must not be blank")
        return value

    @field_validator("observed_at")
    @classmethod
    def utc_timestamp(cls, value):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z", value)
        if not match:
            raise ValueError("Use UTC RFC3339 ending in Z")
        parsed = datetime.fromisoformat(match.group(1) + "Z")
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("Observation must be UTC")
        # Preserve sub-microsecond input precision instead of silently truncating it.
        fraction = (match.group(2) or "").rstrip("0").ljust(6, "0")
        return f"{match.group(1)}.{fraction}Z"

    @model_validator(mode="after")
    def measurements(self):
        names = ("vehicle_count", "average_speed", "occupancy")
        supplied = self.model_fields_set.intersection(names)
        if not supplied or any(getattr(self, name) is None for name in supplied):
            raise ValueError("Supply at least one non-null measurement; omit missing measurements")
        return self

    def canonical(self):
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")

    def to_proto(self):
        from .publisher_pb2 import ReadingEvent
        return ReadingEvent(**self.model_dump(exclude_none=True))

    @classmethod
    def from_proto(cls, message):
        data = {key: getattr(message, key) for key in
                ("schema_version", "event_id", "sensor_id", "intersection_id", "observed_at")}
        for key in ("vehicle_count", "average_speed", "occupancy"):
            if message.HasField(key):
                data[key] = getattr(message, key)
        return cls.model_validate(data)


def archive_key(event_id):
    return f"normalized/v1/{hashlib.sha256(event_id.encode('utf-8')).hexdigest()}.json"
