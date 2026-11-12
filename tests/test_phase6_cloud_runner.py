"""Offline guards for the Phase 6 cloud acceptance runner."""

import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "contracts/python"))

import phase6_cloud  # noqa: E402


class CloudRunnerTests(unittest.TestCase):
    def test_execution_checkpoint_survives_before_teardown(self):
        original = phase6_cloud.EVIDENCE
        with tempfile.TemporaryDirectory() as directory:
            phase6_cloud.EVIDENCE = Path(directory) / "phase-6-cloud.json"
            try:
                evidence = {"run_name": "stp6-checkpoint", "deployment_applied": True,
                            "logs": {"duplicate": True}}
                phase6_cloud.checkpoint_execution(evidence)
                fixed = json.loads(phase6_cloud.EVIDENCE.read_text(encoding="utf-8"))
                run_specific = json.loads((phase6_cloud.EVIDENCE.parent /
                                           "phase-6-cloud-stp6-checkpoint.json").read_text(encoding="utf-8"))
            finally:
                phase6_cloud.EVIDENCE = original
        self.assertTrue(fixed["deployment_applied"])
        self.assertTrue(run_specific["logs"]["duplicate"])

    def test_cleanup_resume_preserves_existing_proof(self):
        original = phase6_cloud.EVIDENCE
        with tempfile.TemporaryDirectory() as directory:
            phase6_cloud.EVIDENCE = Path(directory) / "phase-6-cloud.json"
            run_path = phase6_cloud.EVIDENCE.parent / "phase-6-cloud-stp6-resume.json"
            run_path.write_text(json.dumps({"run_name": "stp6-resume", "logs": {"event_count": 18}}),
                                encoding="utf-8")
            try:
                resumed = phase6_cloud.resume_cleanup_evidence(
                    "stp6-resume", {"started_at": "now", "managed_verified": False})
            finally:
                phase6_cloud.EVIDENCE = original
        self.assertEqual(resumed["logs"]["event_count"], 18)
        self.assertEqual(resumed["cleanup_resumed_at"], "now")

    def test_budget_guard_keeps_the_approved_reserve(self):
        self.assertEqual(phase6_cloud.BUDGET_CAP_USD, 8.00)
        self.assertEqual(phase6_cloud.RESERVED_CLEANUP_USD, 0.50)
        self.assertEqual(phase6_cloud.PREDEPLOYMENT_GATE_USD, 7.50)

    def test_expected_plan_scope(self):
        self.assertEqual(sum(phase6_cloud.EXPECTED.values()), 11)
        self.assertEqual(phase6_cloud.EXPECTED["aws_sqs_queue"], 2)
        self.assertEqual(phase6_cloud.EXPECTED["aws_lambda_event_source_mapping"], 1)

    def test_plan_rejects_changes_outside_exact_create_scope(self):
        changes = []
        for kind, count in phase6_cloud.EXPECTED.items():
            changes.extend({"address": f"{kind}.{index}", "type": kind,
                            "change": {"actions": ["create"]}} for index in range(count))
        self.assertEqual(len(phase6_cloud.review_plan_document({"resource_changes": changes})), 11)
        for altered in (changes[:-1],
                        [{**changes[0], "change": {"actions": ["delete"]}}, *changes[1:]],
                        [*changes, {"address": "aws_vpc.extra", "type": "aws_vpc",
                                    "change": {"actions": ["create"]}}]):
            with self.assertRaises(RuntimeError):
                phase6_cloud.review_plan_document({"resource_changes": altered})

    def test_generated_requests_have_approved_identities(self):
        # The Lambda module is supplied through the same path used by its local tests.
        sys.path.insert(0, str(ROOT / "services/alert-service"))
        from alerts import validate_request

        congestion, incident = phase6_cloud.request_pair("stp6-test")
        self.assertEqual(validate_request(congestion), congestion)
        self.assertEqual(validate_request(incident), incident)
        self.assertNotEqual(congestion["alert_id"], incident["alert_id"])

    def test_cloudwatch_reader_handles_empty_first_page(self):
        class Pages:
            def paginate(self, **kwargs):
                self.assert_equal(kwargs["logGroupName"], "/aws/lambda/test")
                yield {"events": [], "nextToken": "more"}
                yield {"events": [{"message": "outcome=created"}]}

            @staticmethod
            def assert_equal(actual, expected):
                if actual != expected:
                    raise AssertionError((actual, expected))

        class Logs:
            def get_paginator(self, operation):
                self.operation = operation
                return Pages()

        client = Logs()
        self.assertEqual(phase6_cloud.all_log_events(client, "/aws/lambda/test"),
                         [{"message": "outcome=created"}])
        self.assertEqual(client.operation, "filter_log_events")


if __name__ == "__main__":
    unittest.main()
