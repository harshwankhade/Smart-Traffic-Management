from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value


class Patch(Input):
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("supply at least one non-null editable field")
        return self


class IntersectionCreate(Input):
    schema_version: Literal["1.0"] = "1.0"
    intersection_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1)
    location: str = Field(min_length=1)


class Intersection(IntersectionCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class IntersectionPatch(Patch):
    name: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)


class SensorCreate(Input):
    schema_version: Literal["1.0"] = "1.0"
    sensor_id: str = Field(min_length=1, max_length=128)
    intersection_id: str = Field(min_length=1, max_length=128)
    location: str = Field(min_length=1)
    status: Literal["active", "inactive"]


class Sensor(SensorCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SensorPatch(Patch):
    location: str | None = Field(default=None, min_length=1)
    status: Literal["active", "inactive"] | None = None
