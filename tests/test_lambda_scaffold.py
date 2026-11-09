"""The smoke handler must not acknowledge unimplemented queue events."""

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "services/alert-service/handler.py"
SPEC = importlib.util.spec_from_file_location("alert_scaffold", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LambdaScaffoldTests(unittest.TestCase):
    def test_explicit_smoke_event(self):
        self.assertEqual(MODULE.handler({"scaffold_smoke": True}, None),
                         {"service": "alert-service", "status": "ok", "scope": "scaffold"})

    def test_business_events_are_not_acknowledged(self):
        for event in ({}, {"Records": []}, {"scaffold_smoke": False}, None):
            with self.subTest(event=event), self.assertRaises(ValueError):
                MODULE.handler(event, None)
