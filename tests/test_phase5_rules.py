"""Phase 5 pure-rule checks against the approved Flink result contract."""

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "v1"
sys.path.insert(0, str(ROOT / "services" / "signal-recommendation"))

from recommendation import recommend, validate_result  # noqa: E402


def contract(name):
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))


def example(name):
    return json.loads((CONTRACTS / "examples" / f"{name}.json").read_text(encoding="utf-8"))


class RecommendationRulesTests(unittest.TestCase):
    def test_new_contracts_and_examples(self):
        for name in ("recommendation", "summary"):
            with self.subTest(name=name):
                schema = contract(name)
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(example(name))
        self.assertEqual(example("summary"), example("result"))
        self.assertEqual(recommend(example("result")), example("recommendation"))

    def test_all_congestion_actions_are_deterministic(self):
        cases = (
            ("high", 18.5, 0.72, "extend_green", 10, "high_congestion"),
            ("medium", 30, 0.4, "no_adjustment", 0, "medium_congestion"),
            ("low", 45, 0.2, "no_adjustment", 0, "low_congestion"),
            ("unknown", None, None, "no_adjustment", 0, "insufficient_measurements"),
        )
        for level, speed, occupancy, action, seconds, reason in cases:
            with self.subTest(level=level):
                result = example("result")
                result.update(congestion=level, average_speed=speed,
                              average_occupancy=occupancy)
                original = copy.deepcopy(result)
                first = recommend(result)
                self.assertEqual(result, original)
                self.assertEqual(first, recommend(result))
                self.assertEqual((first["action"], first["green_extension_seconds"],
                                  first["reason_code"]), (action, seconds, reason))
                self.assertTrue(first["simulated"])
                Draft202012Validator(contract("recommendation"),
                                     format_checker=FormatChecker()).validate(first)

    def test_missing_measurements_and_threshold_boundaries(self):
        for speed, occupancy, level in (
            (None, None, "unknown"), (None, 0.8, "high"),
            (20, None, "medium"), (40, None, "low"),
            (None, 0.5, "medium"), (None, 0.49, "low"),
        ):
            with self.subTest(speed=speed, occupancy=occupancy):
                data = example("result")
                data.update(average_speed=speed, average_occupancy=occupancy,
                            congestion=level)
                self.assertEqual(validate_result(data), data)

    def test_bad_inputs_are_rejected(self):
        bad = (
            {"window_id": "wrong"},
            {"window_end": "2026-11-09T10:02:00Z"},
            {"window_start": "2026-11-09T10:00:01Z"},
            {"window_start": "2026-11-09T15:30:00+05:30"},
            {"congestion": "low"},
            {"congestion": []},
            {"average_speed": float("nan")},
            {"average_speed": -1},
            {"average_occupancy": 1.1},
            {"average_occupancy": "0.8"},
            {"reading_count": True},
            {"vehicle_count_sum": -1},
            {"schema_version": "2.0"},
            {"unexpected": "field"},
        )
        for change in bad:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    recommend({**example("result"), **change})
        with self.assertRaises(ValueError):
            recommend({"schema_version": "1.0"})


if __name__ == "__main__":
    unittest.main()
