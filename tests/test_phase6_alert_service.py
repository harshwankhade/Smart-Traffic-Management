"""Alert Lambda batch and conditional repository behavior without AWS calls."""

import importlib.util
import json
import logging
import sys
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts/python"))
sys.path.insert(0, str(ROOT / "services/alert-service"))

from alerts import AlertConflict, AlertRepository, validate_request  # noqa: E402
from traffic_contracts.alerts import congestion_request  # noqa: E402
from tests.test_phase5_storage import result  # noqa: E402

spec = importlib.util.spec_from_file_location("phase6_alert_handler", ROOT / "services/alert-service/handler.py")
handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)


def sqs(message_id, request):
    return {"messageId": message_id, "eventSource": "aws:sqs",
            "body": json.dumps(request) if not isinstance(request, str) else request}


class FakeTable:
    def __init__(self):
        self.items = {}
        self.fail = False

    def put_item(self, *, Item, ConditionExpression):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.assert_condition(ConditionExpression)
        key = Item["alert_id"]
        if key in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException",
                                          "Message": "exists"}}, "PutItem")
        self.items[key] = dict(Item)

    def assert_condition(self, condition):
        if condition != "attribute_not_exists(alert_id)":
            raise AssertionError("expected conditional insert")

    def get_item(self, *, Key, ConsistentRead):
        if not ConsistentRead:
            raise AssertionError("replay requires a consistent read")
        return {"Item": self.items[Key["alert_id"]]} if Key["alert_id"] in self.items else {}


class FakeResource:
    def __init__(self):
        self.table = FakeTable()

    def Table(self, name):
        if name != "traffic_alerts":
            raise AssertionError("wrong table")
        return self.table


class AlertServiceTests(unittest.TestCase):
    def setUp(self):
        self.resource = FakeResource()
        self.repo = AlertRepository(resource=self.resource)
        self.request = congestion_request(result("int-1", 0))

    def test_validate_both_sources_and_reject_invalid(self):
        self.assertEqual(validate_request(self.request), self.request)
        incident = {"schema_version": "1.0", "alert_id": "event-1/incident-alert/v1",
                    "source_type": "incident", "source_id": "event-1",
                    "intersection_id": "int-1", "reason": "incident_closure_open",
                    "occurred_at": "2026-11-11T10:00:00Z", "rule_version": "1"}
        self.assertEqual(validate_request(incident), incident)
        for bad in ({**incident, "reason": "wrong"}, {**incident, "extra": 1},
                    {**self.request, "alert_id": "other"},
                    {**self.request, "occurred_at": "yesterday"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_request(bad)

    def test_conditional_insert_replay_conflict(self):
        self.assertEqual(self.repo.put(self.request), "created")
        first = self.repo.get(self.request["alert_id"])
        self.assertEqual(first["outcome"], "recorded")
        self.assertEqual(self.repo.put(self.request), "unchanged")
        self.assertEqual(self.repo.get(self.request["alert_id"]), first)
        incident = {"schema_version": "1.0", "alert_id": "event-1/incident-alert/v1",
                    "source_type": "incident", "source_id": "event-1",
                    "intersection_id": "int-1", "reason": "incident_closure_open",
                    "occurred_at": "2026-11-11T10:00:00Z", "rule_version": "1"}
        self.repo.put(incident)
        with self.assertRaises(AlertConflict):
            self.repo.put({**incident, "intersection_id": "int-2"})

    def test_partial_batch_retries_only_failed_items(self):
        self.assertEqual(handler_module.LOG.getEffectiveLevel(), logging.INFO)
        incident = {"schema_version": "1.0", "alert_id": "event-1/incident-alert/v1",
                    "source_type": "incident", "source_id": "event-1",
                    "intersection_id": "int-1", "reason": "incident_closure_open",
                    "occurred_at": "2026-11-11T10:00:00Z", "rule_version": "1"}
        batch = {"Records": [sqs("m1", self.request), sqs("m2", "{bad"), sqs("m3", incident)]}
        with self.assertLogs(handler_module.LOG, level="INFO") as logs:
            response = handler_module.process_batch(batch, self.repo)
        self.assertEqual(response, {"batchItemFailures": [{"itemIdentifier": "m2"}]})
        self.assertEqual(len(self.resource.table.items), 2)
        self.assertTrue(any("alert_id=" + self.request["alert_id"] in line for line in logs.output))
        self.assertTrue(any("message_id=m2" in line and "error=JSONDecodeError" in line
                            for line in logs.output))
        self.assertFalse(any("{bad" in line for line in logs.output))
        self.assertEqual(handler_module.process_batch({"Records": [sqs("m1", self.request)]}, self.repo),
                         {"batchItemFailures": []})

    def test_storage_failure_and_conflict_are_retried(self):
        self.resource.table.fail = True
        self.assertEqual(handler_module.process_batch({"Records": [sqs("m1", self.request)]}, self.repo),
                         {"batchItemFailures": [{"itemIdentifier": "m1"}]})
        self.resource.table.fail = False
        self.repo.put(self.request)
        incident = {"schema_version": "1.0", "alert_id": "event-1/incident-alert/v1",
                    "source_type": "incident", "source_id": "event-1",
                    "intersection_id": "int-1", "reason": "incident_closure_open",
                    "occurred_at": "2026-11-11T10:00:00Z", "rule_version": "1"}
        self.repo.put(incident)
        self.assertEqual(handler_module.process_batch({"Records": [sqs("m2", {**incident, "intersection_id": "int-2"})]}, self.repo),
                         {"batchItemFailures": [{"itemIdentifier": "m2"}]})

    def test_invalid_envelope_fails_batch(self):
        with self.assertRaises(ValueError):
            handler_module.process_batch({"Records": [{"body": "{}"}]}, self.repo)


if __name__ == "__main__":
    unittest.main()
