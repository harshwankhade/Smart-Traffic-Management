"""Opt-in AWS DynamoDB verification using the existing Phase 5 repositories."""

import os
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts" / "python"))
sys.path.insert(0, str(ROOT / "services" / "signal-recommendation"))
sys.path.insert(0, str(ROOT / "services" / "traffic-analytics"))

from analytics.repository import SummaryRepository  # noqa: E402
from recommendation import recommend  # noqa: E402
from recommendation.repository import RecommendationRepository  # noqa: E402
from tests.test_phase5_storage import result  # noqa: E402
from traffic_contracts.dynamo_store import RecordConflict  # noqa: E402


def wait_for(check, label, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, httpx.HTTPError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {label}")


@unittest.skipUnless(os.getenv("PHASE5_MANAGED_DYNAMODB_TEST") == "1",
                     "set only from the approved managed verification runner")
class ManagedDynamoDbTests(unittest.TestCase):
    def test_service_repositories_write_read_query_and_replay(self):
        run = os.environ.get("PHASE5_MANAGED_RUN_ID")
        self.assertIsNotNone(run)
        self.assertFalse(os.getenv("DYNAMODB_ENDPOINT_URL"), "managed test must not use DynamoDB Local")
        self.assertEqual(os.getenv("RECOMMENDATIONS_TABLE"), f"{run}-recommendations")
        self.assertEqual(os.getenv("SUMMARIES_TABLE"), f"{run}-summaries")

        recommendations = RecommendationRepository()
        summaries = SummaryRepository()
        recommendations.store.ready()
        summaries.store.ready()
        intersection = f"{run}-managed"
        other = f"{run}-other"
        windows = [result(intersection, minute) for minute in range(3)]
        other_window = result(other, 0)

        for window in windows:
            recommendation = recommend(window)
            self.assertEqual(summaries.put(window), "created")
            self.assertEqual(recommendations.put(recommendation), "created")
            self.assertEqual(summaries.put(window), "unchanged")
            self.assertEqual(recommendations.put(recommendation), "unchanged")

        self.assertEqual(summaries.get(intersection, windows[0]["window_id"])["window_id"],
                         windows[0]["window_id"])
        self.assertEqual(recommendations.get(intersection, recommend(windows[0])["recommendation_id"])[
            "green_extension_seconds"], 10)
        first, cursor = summaries.query(intersection, limit=1)
        self.assertEqual([item["window_id"] for item in first], [windows[0]["window_id"]])
        second, _ = summaries.query(intersection, limit=1, exclusive_start_key=cursor)
        self.assertEqual([item["window_id"] for item in second], [windows[1]["window_id"]])
        scoped, _ = recommendations.query(intersection, from_start=windows[1]["window_start"],
                                          to_start=windows[2]["window_start"])
        self.assertEqual([item["window_id"] for item in scoped], [windows[1]["window_id"]])

        changed = {**windows[0], "vehicle_count_sum": 6}
        with self.assertRaises(RecordConflict):
            summaries.put(changed)
        with self.assertRaises(RecordConflict):
            recommendations.put(recommend(changed))
        self.assertEqual(summaries.get(intersection, windows[0]["window_id"])["vehicle_count_sum"], 5)

        self.assertEqual(summaries.put(other_window), "created")
        self.assertEqual(recommendations.put(recommend(other_window)), "created")

        processes = []
        outputs = []

        def start(name, directory):
            port_file = Path(directory) / f"{name}-port.json"
            output = open(Path(directory) / f"{name}.log", "w", encoding="utf-8")
            environment = os.environ.copy()
            environment["PHASE5_CONSUMER_ENABLED"] = "0"
            environment.pop("DYNAMODB_ENDPOINT_URL", None)
            process = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run_service.py"), name,
                                        "--port", "0", "--port-file", str(port_file)],
                                       cwd=ROOT, env=environment, stdout=output,
                                       stderr=subprocess.STDOUT)
            processes.append(process)
            outputs.append(output)
            port = wait_for(lambda: json.loads(port_file.read_text(encoding="utf-8"))["port"]
                            if port_file.exists() else None, f"{name} port")
            base = f"http://127.0.0.1:{port}"
            wait_for(lambda: httpx.get(base + "/healthz", timeout=2, trust_env=False).status_code == 200,
                     f"{name} HTTP")
            return base

        try:
            with tempfile.TemporaryDirectory(prefix="p5-managed-", ignore_cleanup_errors=True) as directory:
                recommendation_api = start("signal-recommendation", directory)
                analytics_api = start("traffic-analytics", directory)
                with httpx.Client(timeout=20, trust_env=False) as client:
                    for base, list_path, detail_path, identifier in (
                        (recommendation_api, "/recommendations", "/recommendations/",
                         recommend(windows[0])["recommendation_id"]),
                        (analytics_api, "/traffic/summaries", "/traffic/summaries/",
                         windows[0]["window_id"]),
                    ):
                        first = client.get(base + list_path, params={"intersection_id": intersection,
                                                                     "limit": 1})
                        self.assertEqual(first.status_code, 200)
                        page = first.json()
                        self.assertEqual([item["window_id"] for item in page["items"]],
                                         [windows[0]["window_id"]])
                        self.assertIsInstance(page["next_cursor"], str)
                        second = client.get(base + list_path, params={"intersection_id": intersection,
                                                                      "limit": 1,
                                                                      "cursor": page["next_cursor"]})
                        self.assertEqual(second.status_code, 200)
                        self.assertEqual([item["window_id"] for item in second.json()["items"]],
                                         [windows[1]["window_id"]])
                        scoped = client.get(base + list_path, params={
                            "intersection_id": intersection,
                            "from": windows[1]["window_start"], "to": windows[2]["window_start"]})
                        self.assertEqual([item["window_id"] for item in scoped.json()["items"]],
                                         [windows[1]["window_id"]])
                        isolated = client.get(base + list_path, params={"intersection_id": other})
                        self.assertEqual([item["window_id"] for item in isolated.json()["items"]],
                                         [other_window["window_id"]])
                        detail = client.get(base + detail_path + quote(identifier, safe=""),
                                            params={"intersection_id": intersection})
                        self.assertEqual(detail.status_code, 200)
                        self.assertEqual(detail.json()["window_id"], windows[0]["window_id"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for output in outputs:
                output.close()


if __name__ == "__main__":
    unittest.main()
