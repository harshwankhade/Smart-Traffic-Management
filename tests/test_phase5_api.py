"""Real HTTP and DynamoDB Local checks for the Phase 5 read APIs."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts" / "python"))
sys.path.insert(0, str(ROOT / "services" / "signal-recommendation"))
sys.path.insert(0, str(ROOT / "services" / "traffic-analytics"))

from analytics.repository import SummaryRepository  # noqa: E402
from recommendation import recommend  # noqa: E402
from recommendation.repository import RecommendationRepository  # noqa: E402
from tests.test_phase5_storage import result  # noqa: E402


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
    raise AssertionError(f"Timed out waiting for {label}")


@unittest.skipUnless(os.getenv("PHASE5_DYNAMODB_API_TEST") == "1",
                     "set PHASE5_DYNAMODB_API_TEST=1 after starting DynamoDB Local")
class Phase5ApiTests(unittest.TestCase):
    def test_real_http_filters_cursors_and_storage_errors(self):
        resource = boto3.resource("dynamodb", endpoint_url="http://127.0.0.1:8000",
                                  region_name="ap-south-1", aws_access_key_id="local",
                                  aws_secret_access_key="local")
        recommendations = RecommendationRepository(resource=resource)
        summaries = SummaryRepository(resource=resource)
        intersection = "p5-api-" + uuid.uuid4().hex[:12]
        other = intersection + "-other"
        windows = [result(intersection, minute) for minute in range(3)]
        windows.append(result(other, 0))
        windows[0]["average_speed"] = Decimal("18.123456789012345678901")
        processes = []
        outputs = []
        dynamodb_running = True

        def compose(*args):
            subprocess.run(["docker", "compose", "-p", "smarttraffic-phase5", "-f",
                            str(ROOT / "infrastructure/local/phase5/compose.yaml"), *args],
                           cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

        def start(name, directory):
            port_file = Path(directory) / f"{name}-port.json"
            output = open(Path(directory) / f"{name}.log", "w", encoding="utf-8")
            env = os.environ.copy()
            env.update(PHASE5_CONSUMER_ENABLED="0", DYNAMODB_ENDPOINT_URL="http://127.0.0.1:8000")
            proc = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_service.py"), name,
                                     "--port", "0", "--port-file", str(port_file)],
                                    cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
            processes.append(proc)
            outputs.append(output)
            port = wait_for(lambda: json.loads(port_file.read_text())["port"]
                            if port_file.exists() else None, f"{name} port")
            base = f"http://127.0.0.1:{port}"
            wait_for(lambda: httpx.get(base + "/healthz", timeout=2, trust_env=False).status_code == 200,
                     f"{name} HTTP")
            return base

        with tempfile.TemporaryDirectory(prefix="p5-api-") as directory:
            try:
                for window in windows:
                    self.assertEqual(summaries.put(window), "created")
                    self.assertEqual(recommendations.put(recommend(window)), "created")
                rec_base = start("signal-recommendation", directory)
                sum_base = start("traffic-analytics", directory)

                with httpx.Client(timeout=20, trust_env=False) as client:
                    def get(base, path, **params):
                        return client.get(base + path, params=params)

                    for base, list_path, detail_path, identifier in (
                        (rec_base, "/recommendations", "/recommendations/", windows[0]["window_id"] + "/recommendation/v1"),
                        (sum_base, "/traffic/summaries", "/traffic/summaries/", windows[0]["window_id"]),
                    ):
                        document = get(base, "/openapi.json")
                        self.assertEqual(document.status_code, 200)
                        self.assertIn(list_path, document.json()["paths"])
                        self.assertEqual(get(base, list_path).status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=" ").status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=intersection, limit=0).status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=intersection, limit=101).status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=intersection,
                                             cursor="not-valid***").status_code, 422)

                        first = get(base, list_path, intersection_id=intersection, limit=1)
                        self.assertEqual(first.status_code, 200)
                        page = first.json()
                        self.assertEqual(len(page["items"]), 1)
                        self.assertIsInstance(page["next_cursor"], str)
                        second = get(base, list_path, intersection_id=intersection, limit=1,
                                     cursor=page["next_cursor"])
                        self.assertEqual(second.status_code, 200)
                        self.assertEqual(second.json()["items"][0]["window_id"], windows[1]["window_id"])
                        self.assertEqual(get(base, list_path, intersection_id=other, limit=1,
                                             cursor=page["next_cursor"]).status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=intersection, limit=2,
                                             cursor=page["next_cursor"]).status_code, 422)

                        scoped = get(base, list_path, intersection_id=intersection,
                                     **{"from": "2026-11-09T10:00:00.0000001Z",
                                        "to": "2026-11-09T10:02:00Z"})
                        self.assertEqual(scoped.status_code, 200)
                        self.assertEqual([item["window_id"] for item in scoped.json()["items"]],
                                         [windows[1]["window_id"]])
                        self.assertEqual(len(get(base, list_path, intersection_id=intersection,
                                                 to="2026-11-09T10:00:00.0000001Z").json()["items"]), 1)
                        self.assertEqual(get(base, list_path, intersection_id=intersection,
                                             **{"from": "2026-11-09T10:00:05Z",
                                                "to": "2026-11-09T10:00:40Z"}).json(),
                                         {"items": [], "next_cursor": None})
                        self.assertEqual(get(base, list_path, intersection_id=intersection,
                                             **{"from": "2026-11-09T10:01:00Z",
                                                "to": "2026-11-09T10:01:00Z"}).status_code, 422)
                        self.assertEqual(get(base, list_path, intersection_id=intersection,
                                             **{"from": "2026-11-09T15:30:00+05:30"}).status_code, 422)
                        self.assertEqual(len(get(base, list_path, intersection_id=other).json()["items"]), 1)

                        detail = get(base, detail_path + quote(identifier, safe=""),
                                     intersection_id=intersection)
                        self.assertEqual(detail.status_code, 200)
                        self.assertEqual(detail.json()["window_id"], windows[0]["window_id"])
                        self.assertEqual(get(base, detail_path + quote(identifier, safe=""),
                                             intersection_id=other).status_code, 422)
                        missing_id = result(intersection, 3)["window_id"]
                        if base == rec_base:
                            missing_id += "/recommendation/v1"
                        self.assertEqual(get(base, detail_path + quote(missing_id, safe=""),
                                             intersection_id=intersection).status_code, 404)

                    exact = get(sum_base, "/traffic/summaries/" + quote(windows[0]["window_id"], safe=""),
                                intersection_id=intersection)
                    parsed = json.loads(exact.text, parse_float=Decimal)
                    self.assertEqual(parsed["average_speed"], Decimal("18.123456789012345678901"))

                    compose("stop", "dynamodb")
                    dynamodb_running = False
                    self.assertEqual(get(rec_base, "/recommendations", intersection_id=intersection).status_code, 503)
                    self.assertEqual(get(sum_base, "/traffic/summaries", intersection_id=intersection).status_code, 503)
                    for base in (rec_base, sum_base):
                        self.assertEqual(get(base, "/healthz").status_code, 200)
                    compose("start", "dynamodb")
                    dynamodb_running = True
                    wait_for(lambda: resource.meta.client.list_tables(), "DynamoDB recovery")
                    self.assertEqual(get(rec_base, "/recommendations", intersection_id=intersection).status_code, 200)
                    self.assertEqual(get(sum_base, "/traffic/summaries", intersection_id=intersection).status_code, 200)
            finally:
                for proc in processes:
                    if proc.poll() is None:
                        proc.terminate()
                for proc in processes:
                    try:
                        proc.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                for output in outputs:
                    output.close()
                if not dynamodb_running:
                    compose("start", "dynamodb")
                    wait_for(lambda: resource.meta.client.list_tables(), "DynamoDB cleanup")
                for window in windows:
                    key = {"intersection_id": window["intersection_id"],
                           "window_key": f"{window['window_start']}#{window['window_id']}"}
                    recommendations.store.table.delete_item(Key=key)
                    summaries.store.table.delete_item(Key=key)


if __name__ == "__main__":
    unittest.main()
