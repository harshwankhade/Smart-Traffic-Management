from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value


class IncidentCreate(Input):
    schema_version: Literal["1.0"] = "1.0"
    incident_id: str = Field(min_length=1, max_length=128)
    intersection_id: str = Field(min_length=1, max_length=128)
    type: Literal["collision", "closure", "disruption"]
    description: str = Field(min_length=1, max_length=2000)


class Incident(IncidentCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    event_id: str
    status: Literal["open", "resolved"]
    reported_at: datetime
    updated_at: datetime

    @field_serializer("reported_at", "updated_at")
    def utc_timestamp(self, value):
        if value.tzinfo is None:  # SQLite drops timezone metadata; stored values are UTC.
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class IncidentPatch(Input):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Literal["open", "resolved"] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("supply at least one non-null editable field")
        return self
