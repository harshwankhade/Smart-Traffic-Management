"""The original smoke entry point remains while SQS batches are supported."""

import importlib.util
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "services/alert-service/handler.py"
sys.path.insert(0, str(SOURCE.parent))
sys.path.insert(0, str(SOURCE.parents[2] / "contracts/python"))
SPEC = importlib.util.spec_from_file_location("alert_scaffold", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LambdaScaffoldTests(unittest.TestCase):
    def test_explicit_smoke_event(self):
        self.assertEqual(MODULE.handler({"scaffold_smoke": True}, None),
                         {"service": "alert-service", "status": "ok", "scope": "scaffold"})

    def test_invalid_events_are_not_acknowledged(self):
        for event in ({}, {"scaffold_smoke": False}, None):
            with self.subTest(event=event), self.assertRaises(ValueError):
                MODULE.handler(event, None)

    def test_empty_batch_has_no_failures(self):
        self.assertEqual(MODULE.handler({"Records": []}, None), {"batchItemFailures": []})
