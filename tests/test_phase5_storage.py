"""Opt-in real DynamoDB Local repository verification for Phase 5 Step 3."""

import os
import subprocess
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from botocore.exceptions import ConnectionClosedError, EndpointConnectionError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts" / "python"))
sys.path.insert(0, str(ROOT / "services" / "signal-recommendation"))
sys.path.insert(0, str(ROOT / "services" / "traffic-analytics"))

from analytics.repository import SummaryRepository  # noqa: E402
from recommendation import recommend  # noqa: E402
from recommendation.repository import RecommendationRepository  # noqa: E402
from traffic_contracts.dynamo_store import RecordConflict, resource_from_environment  # noqa: E402


def result(intersection, minute):
    start = datetime(2026, 11, 9, 10, minute, tzinfo=timezone.utc)
    end = start + timedelta(minutes=1)
    first = start.strftime("%Y-%m-%dT%H:%M:00Z")
    last = end.strftime("%Y-%m-%dT%H:%M:00Z")
    return {"schema_version": "1.0", "window_id": f"{intersection}/{first}/{last}/v1",
            "intersection_id": intersection, "window_start": first, "window_end": last,
            "reading_count": 1, "vehicle_count_sum": 5, "average_speed": 18.5,
            "average_occupancy": 0.72, "congestion": "high"}


@unittest.skipUnless(os.getenv("PHASE5_DYNAMODB_LOCAL_TEST") == "1",
                     "set PHASE5_DYNAMODB_LOCAL_TEST=1 after phase5_local.py up/bootstrap")
class LocalStorageTests(unittest.TestCase):
    def test_real_local_persistence_replay_queries_and_restart(self):
        old_endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL")
        os.environ["DYNAMODB_ENDPOINT_URL"] = "http://127.0.0.1:8000"
        resource = resource_from_environment()
        recs = RecommendationRepository(resource=resource)
        summaries = SummaryRepository(resource=resource)
        intersection = "p5-storage-" + uuid.uuid4().hex[:12]
        other = intersection + "-other"
        inputs = [result(intersection, minute) for minute in range(3)]
        inputs.append(result(other, 1))
        try:
            for item in inputs:
                self.assertEqual(summaries.put(item), "created")
                self.assertEqual(recs.put(recommend(item)), "created")
                self.assertEqual(summaries.put(item), "unchanged")
                self.assertEqual(recs.put(recommend(item)), "unchanged")

            conflicting = {**inputs[0], "vehicle_count_sum": 6}
            with self.assertRaises(RecordConflict):
                summaries.put(conflicting)
            with self.assertRaises(RecordConflict):
                recs.put(recommend(conflicting))
            self.assertEqual(summaries.get(intersection, inputs[0]["window_id"])["vehicle_count_sum"], 5)
            self.assertEqual(recs.get(intersection, recommend(inputs[0])["recommendation_id"])["source_result"]["vehicle_count_sum"], 5)

            first_page, cursor = summaries.query(intersection, limit=1)
            self.assertEqual(len(first_page), 1)
            self.assertIsNotNone(cursor)
            second_page, _ = summaries.query(intersection, limit=1, exclusive_start_key=cursor)
            self.assertEqual(second_page[0]["window_id"], inputs[1]["window_id"])
            scoped, _ = summaries.query(intersection, from_start=inputs[1]["window_start"],
                                        to_start=inputs[2]["window_start"])
            self.assertEqual([x["window_id"] for x in scoped], [inputs[1]["window_id"]])
            other_recs, _ = recs.query(other)
            self.assertEqual(len(other_recs), 1)
            self.assertEqual(len(recs.query(intersection)[0]), 3)
            with self.assertRaises(ValueError):
                summaries.query(intersection, exclusive_start_key={"intersection_id": other,
                                                              "window_key": "x"})
            with self.assertRaises(ValueError):
                summaries.put({**inputs[0], "vehicle_count_sum": 10 ** 40})

            subprocess.run(["docker", "compose", "-p", "smarttraffic-phase5", "-f",
                            str(ROOT / "infrastructure/local/phase5/compose.yaml"),
                            "restart", "dynamodb"], check=True, cwd=ROOT,
                           stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 30
            while True:
                try:
                    resource_from_environment().meta.client.list_tables()
                    break
                except (ConnectionClosedError, EndpointConnectionError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("DynamoDB Local did not recover after restart")
                    time.sleep(0.5)
            # Reopen from a fresh client after the container process restarts.
            reopened = resource_from_environment()
            self.assertEqual(SummaryRepository(resource=reopened).get(
                intersection, inputs[2]["window_id"])["window_id"], inputs[2]["window_id"])
            self.assertEqual(RecommendationRepository(resource=reopened).put(
                recommend(inputs[2])), "unchanged")
        finally:
            for item in inputs:
                key = {"intersection_id": item["intersection_id"],
                       "window_key": f"{item['window_start']}#{item['window_id']}"}
                summaries.store.table.delete_item(Key=key)
                recs.store.table.delete_item(Key=key)
            if old_endpoint is None:
                os.environ.pop("DYNAMODB_ENDPOINT_URL", None)
            else:
                os.environ["DYNAMODB_ENDPOINT_URL"] = old_endpoint


if __name__ == "__main__":
    unittest.main()
