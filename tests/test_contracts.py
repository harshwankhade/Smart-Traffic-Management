"""Validate draft wire examples without implementing domain services."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1] / "contracts" / "v1"


def load(name, example=False):
    path = ROOT / "examples" / f"{name}.json" if example else ROOT / f"{name}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name):
    return Draft202012Validator(load(name), format_checker=FormatChecker())


class ContractTests(unittest.TestCase):
    def test_all_schemas_and_examples(self):
        for name in ("intersection", "sensor", "reading", "result", "incident", "alert", "alert-request", "alert-outcome"):
            with self.subTest(contract=name):
                Draft202012Validator.check_schema(load(name))
                validator(name).validate(load(name, example=True))

    def test_reading_requires_a_measurement(self):
        reading = load("reading", example=True)
        for key in ("vehicle_count", "average_speed", "occupancy"):
            reading.pop(key)
        self.assertFalse(validator("reading").is_valid(reading))

    def test_single_measurement_and_zero_are_valid(self):
        base = load("reading", example=True)
        for key in ("vehicle_count", "average_speed", "occupancy"):
            base.pop(key)
        for key in ("vehicle_count", "average_speed", "occupancy"):
            with self.subTest(measurement=key):
                self.assertTrue(validator("reading").is_valid({**base, key: 0}))

    def test_invalid_readings(self):
        for field, value in (("vehicle_count", -1), ("vehicle_count", 1.5),
                             ("average_speed", -0.1), ("occupancy", 1.01),
                             ("occupancy", -0.01), ("occupancy", None),
                             ("event_id", ""), ("schema_version", "2.0"),
                             ("observed_at", "yesterday"),
                             ("observed_at", "2026-11-09T10:00:00+05:30"),
                             ("unexpected", "field")):
            with self.subTest(field=field, value=value):
                data = {**load("reading", example=True), field: value}
                self.assertFalse(validator("reading").is_valid(data))

    def test_required_ids_and_versions(self):
        for name in ("intersection", "sensor", "reading", "result", "incident", "alert"):
            data = load(name, example=True)
            for key in load(name)["required"]:
                with self.subTest(contract=name, missing=key):
                    missing = copy.deepcopy(data)
                    missing.pop(key)
                    self.assertFalse(validator(name).is_valid(missing))

    def test_invalid_states_and_types(self):
        for name, field, value in (("sensor", "status", "deleted"),
                                   ("incident", "status", "unrecognized"),
                                   ("incident", "type", "real_dispatch"),
                                   ("result", "congestion", "critical"),
                                   ("alert", "source_type", "other")):
            with self.subTest(contract=name, field=field):
                data = {**load(name, example=True), field: value}
                self.assertFalse(validator(name).is_valid(data))

    def test_result_supports_missing_measurements(self):
        data = load("result", example=True)
        data.update(vehicle_count_sum=5, average_speed=None,
                    average_occupancy=None, congestion="unknown")
        validator("result").validate(data)


if __name__ == "__main__":
    unittest.main()
