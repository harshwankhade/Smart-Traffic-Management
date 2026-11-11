"""Opt-in local Phase 5 demo: Kafka results -> two owners -> HTTP reads."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote

import boto3
import httpx
from confluent_kafka import Producer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts" / "python"))
sys.path.insert(0, str(ROOT / "services" / "signal-recommendation"))
sys.path.insert(0, str(ROOT / "services" / "traffic-analytics"))

from analytics.repository import SummaryRepository  # noqa: E402
from recommendation.repository import RecommendationRepository  # noqa: E402
from tests.test_phase5_storage import result  # noqa: E402


def wait_for(check, label, seconds=45):
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


@unittest.skipUnless(os.getenv("PHASE5_LOCAL_DEMO") == "1",
                     "set PHASE5_LOCAL_DEMO=1 after starting local Kafka and DynamoDB")
class Phase5LocalDemo(unittest.TestCase):
    def test_kafka_to_dynamodb_to_http_replay_and_restart(self):
        run_id = uuid.uuid4().hex[:12]
        intersection = "p5-demo-" + run_id
        resource = boto3.resource("dynamodb", endpoint_url="http://127.0.0.1:8000",
                                  region_name="ap-south-1", aws_access_key_id="local",
                                  aws_secret_access_key="local")
        summaries = SummaryRepository(resource=resource)
        recommendations = RecommendationRepository(resource=resource)
        producer = Producer({"bootstrap.servers": "127.0.0.1:9092",
                             "enable.idempotence": True, "acks": "all"})
        processes, outputs, windows = {}, {}, []

        def start(name, directory):
            port_file = Path(directory) / f"{name}.json"
            port_file.unlink(missing_ok=True)
            output = open(Path(directory) / f"{name}.log", "a", encoding="utf-8")
            env = os.environ.copy()
            env.update(PHASE5_CONSUMER_ENABLED="1",
                       PHASE5_CONSUMER_GROUP_PREFIX="p5-demo-" + run_id + "-",
                       PHASE5_KAFKA_OFFSET_RESET="latest",
                       DYNAMODB_ENDPOINT_URL="http://127.0.0.1:8000",
                       KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:9092",
                       KAFKA_AUTH_MODE="local", KAFKA_RESULTS_TOPIC="traffic.results")
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts/run_service.py"), name, "--port", "0",
                 "--port-file", str(port_file)], cwd=ROOT, env=env,
                stdout=output, stderr=subprocess.STDOUT)
            processes[name], outputs[name] = process, output
            port = wait_for(lambda: json.loads(port_file.read_text())["port"]
                            if port_file.exists() else None, f"{name} port")
            base = f"http://127.0.0.1:{port}"
            wait_for(lambda: httpx.get(base + "/readyz", timeout=2, trust_env=False).status_code == 200,
                     f"{name} readiness", seconds=90)
            return base

        def stop_services():
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
            for process in processes.values():
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            processes.clear()
            for output in outputs.values():
                output.close()
            outputs.clear()

        def publish(payload):
            failures = []
            producer.produce("traffic.results", key=intersection.encode(),
                             value=json.dumps(payload).encode(),
                             on_delivery=lambda error, _: failures.append(error) if error else None)
            self.assertEqual(producer.flush(10), 0)
            self.assertFalse(failures)

        with tempfile.TemporaryDirectory(prefix="p5-demo-", ignore_cleanup_errors=True) as directory:
            try:
                bases = {name: start(name, directory)
                         for name in ("signal-recommendation", "traffic-analytics")}
                first = result(intersection, 0)
                windows.append(first)
                publish(first)
                wait_for(lambda: summaries.get(intersection, first["window_id"]) and
                         recommendations.get(intersection, first["window_id"] + "/recommendation/v1"),
                         "both persisted records")

                # Independently stated known-result expectation, not derived from service code.
                expected = {"action": "extend_green", "green_extension_seconds": 10,
                            "simulated": True}
                with httpx.Client(timeout=10, trust_env=False) as client:
                    summary = client.get(bases["traffic-analytics"] + "/traffic/summaries/" +
                                         quote(first["window_id"], safe=""),
                                         params={"intersection_id": intersection})
                    recommendation = client.get(bases["signal-recommendation"] + "/recommendations/" +
                                                quote(first["window_id"] + "/recommendation/v1", safe=""),
                                                params={"intersection_id": intersection})
                    self.assertEqual(summary.status_code, 200)
                    self.assertEqual(recommendation.status_code, 200)
                    self.assertEqual({key: recommendation.json()[key] for key in expected}, expected)
                    self.assertEqual(recommendation.json()["source_result"]["congestion"], "high")

                    publish(first)  # At-least-once replay must leave one logical record.
                    wait_for(lambda: all(client.get(base + "/readyz").json().get("duplicates", 0) >= 1
                                         for base in bases.values()), "duplicate handling")
                    self.assertEqual(len(client.get(bases["traffic-analytics"] + "/traffic/summaries",
                                                    params={"intersection_id": intersection}).json()["items"]), 1)
                    self.assertEqual(len(client.get(bases["signal-recommendation"] + "/recommendations",
                                                    params={"intersection_id": intersection}).json()["items"]), 1)

                stop_services()
                bases = {name: start(name, directory)
                         for name in ("signal-recommendation", "traffic-analytics")}
                with httpx.Client(timeout=10, trust_env=False) as client:
                    self.assertEqual(client.get(bases["traffic-analytics"] + "/traffic/summaries",
                                                params={"intersection_id": intersection}).json()["items"][0]["window_id"],
                                     first["window_id"])
                    self.assertEqual(client.get(bases["signal-recommendation"] + "/recommendations",
                                                params={"intersection_id": intersection}).json()["items"][0]["recommendation_id"],
                                     first["window_id"] + "/recommendation/v1")
            finally:
                stop_services()
                for item in windows:
                    key = {"intersection_id": intersection,
                           "window_key": f"{item['window_start']}#{item['window_id']}"}
                    summaries.store.table.delete_item(Key=key)
                    recommendations.store.table.delete_item(Key=key)


if __name__ == "__main__":
    unittest.main()
