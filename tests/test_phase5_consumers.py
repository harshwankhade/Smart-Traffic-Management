"""Opt-in Kafka to DynamoDB Local test for Phase 5 result consumers."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

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


def wait_for(check, message, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, httpx.HTTPError):
            pass
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {message}")


@unittest.skipUnless(os.getenv("PHASE5_KAFKA_DYNAMO_TEST") == "1",
                     "set PHASE5_KAFKA_DYNAMO_TEST=1 after starting local Kafka and DynamoDB")
class ConsumerIntegrationTests(unittest.TestCase):
    def test_two_groups_replay_outage_restart_invalid_and_conflict(self):
        run_id = uuid.uuid4().hex[:12]
        intersection = "p5-consumer-" + run_id
        service_names = ("signal-recommendation", "traffic-analytics")
        resource = boto3.resource("dynamodb", endpoint_url="http://127.0.0.1:8000",
                                  region_name="ap-south-1", aws_access_key_id="local",
                                  aws_secret_access_key="local")
        recommendations = RecommendationRepository(resource=resource)
        summaries = SummaryRepository(resource=resource)
        producer = Producer({"bootstrap.servers": "127.0.0.1:9092",
                             "enable.idempotence": True, "acks": "all"})
        produced = []
        processes = {}
        logs = {}
        dynamodb_running = True

        def compose(*args):
            subprocess.run(["docker", "compose", "-p", "smarttraffic-phase5", "-f",
                            str(ROOT / "infrastructure/local/phase5/compose.yaml"),
                            *args], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

        def start(name, directory):
            port_file = Path(directory) / f"{name}-port.json"
            port_file.unlink(missing_ok=True)
            output = open(Path(directory) / f"{name}.log", "a", encoding="utf-8")
            env = os.environ.copy()
            env.update(PHASE5_CONSUMER_ENABLED="1",
                       PHASE5_CONSUMER_GROUP_PREFIX="p5-test-" + run_id + "-",
                       PHASE5_KAFKA_OFFSET_RESET="latest",
                       DYNAMODB_ENDPOINT_URL="http://127.0.0.1:8000",
                       KAFKA_BOOTSTRAP_SERVERS="127.0.0.1:9092",
                       KAFKA_AUTH_MODE="local", KAFKA_RESULTS_TOPIC="traffic.results")
            proc = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_service.py"),
                                     name, "--port", "0", "--port-file", str(port_file)],
                                    cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
            processes[name] = proc
            logs[name] = output
            port = wait_for(lambda: json.loads(port_file.read_text())["port"]
                            if port_file.exists() else None, f"{name} port")
            base = f"http://127.0.0.1:{port}"
            try:
                wait_for(lambda: httpx.get(base + "/readyz", timeout=2, trust_env=False).status_code == 200,
                         f"{name} readiness", seconds=90)
            except AssertionError:
                output.flush()
                details = (Path(directory) / f"{name}.log").read_text(encoding="utf-8")[-2500:]
                raise AssertionError(f"{name} did not become ready; log tail:\n{details}") from None
            self.assertEqual(httpx.get(base + "/healthz", trust_env=False).json(),
                             {"service": name, "status": "ok", "scope": "scaffold"})
            return base

        def stop_all():
            for proc in processes.values():
                if proc.poll() is None:
                    proc.terminate()
            for proc in processes.values():
                try:
                    proc.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            processes.clear()
            for output in logs.values():
                output.close()
            logs.clear()

        def publish(payload):
            errors = []
            value = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            producer.produce("traffic.results", key=intersection.encode(), value=value,
                             on_delivery=lambda error, _: errors.append(error) if error else None)
            self.assertEqual(producer.flush(10), 0)
            self.assertFalse(errors)

        def both_present(item):
            return (summaries.get(intersection, item["window_id"])
                    and recommendations.get(intersection, item["window_id"] + "/recommendation/v1"))

        with tempfile.TemporaryDirectory(prefix="p5-consumers-") as directory:
            try:
                bases = {name: start(name, directory) for name in service_names}
                first = result(intersection, 0)
                produced.append(first)
                publish(first)
                wait_for(lambda: both_present(first), "both first records")
                publish(first)
                try:
                    wait_for(lambda: all(httpx.get(base + "/readyz", trust_env=False).json().get("duplicates", 0) >= 1
                                         for base in bases.values()), "duplicate replay counters")
                except AssertionError:
                    details = {}
                    for name, base in bases.items():
                        logs[name].flush()
                        details[name] = {"ready": httpx.get(base + "/readyz", trust_env=False).text,
                                         "log": (Path(directory) / f"{name}.log").read_text(encoding="utf-8")[-1800:]}
                    raise AssertionError(f"Duplicate replay diagnostics: {details}") from None
                self.assertEqual(len(summaries.query(intersection)[0]), 1)
                self.assertEqual(len(recommendations.query(intersection)[0]), 1)

                publish(b'{"schema_version":"1.0","window_id":"bad"}')
                second = result(intersection, 1)
                produced.append(second)
                publish(second)
                wait_for(lambda: both_present(second), "valid record after malformed input")
                self.assertTrue(all(httpx.get(base + "/readyz", trust_env=False).json().get("invalid", 0) >= 1
                                    for base in bases.values()))
                self.assertTrue(all(httpx.get(base + "/readyz", trust_env=False).json().get("committed", 0) >= 4
                                    for base in bases.values()))

                compose("stop", "dynamodb")
                dynamodb_running = False
                third = result(intersection, 2)
                produced.append(third)
                publish(third)
                wait_for(lambda: all((response := httpx.get(base + "/readyz", trust_env=False)).status_code == 503
                                     and response.json().get("retry", 0) >= 1
                                     for base in bases.values()), "storage outage and uncommitted retry")
                stop_all()  # The third offset must remain uncommitted.
                compose("start", "dynamodb")
                dynamodb_running = True
                wait_for(lambda: resource.meta.client.list_tables(), "DynamoDB restart")
                bases = {name: start(name, directory) for name in service_names}
                try:
                    wait_for(lambda: both_present(third), "replay after process/storage restart", seconds=45)
                except AssertionError:
                    details = {}
                    for name, base in bases.items():
                        logs[name].flush()
                        details[name] = {"ready": httpx.get(base + "/readyz", trust_env=False).text,
                                         "log": (Path(directory) / f"{name}.log").read_text(encoding="utf-8")[-2200:]}
                    raise AssertionError(f"Restart replay diagnostics: {details}") from None
                self.assertEqual(len(summaries.query(intersection)[0]), 3)
                self.assertEqual(len(recommendations.query(intersection)[0]), 3)

                publish({**first, "vehicle_count_sum": 6})
                wait_for(lambda: all(httpx.get(base + "/readyz", trust_env=False).status_code == 503
                                     for base in bases.values()), "conflict quarantine")
                self.assertEqual(summaries.get(intersection, first["window_id"])["vehicle_count_sum"], 5)
                fourth = result(intersection, 3)
                produced.append(fourth)
                publish(fourth)
                time.sleep(1)
                self.assertIsNone(summaries.get(intersection, fourth["window_id"]))
                self.assertIsNone(recommendations.get(intersection, fourth["window_id"] + "/recommendation/v1"))
                stop_all()
                for name in service_names:
                    content = (Path(directory) / f"{name}.log").read_text(encoding="utf-8")
                    self.assertIn("invalid result at traffic.results", content)
                    self.assertIn("conflicting result quarantined", content)
            finally:
                stop_all()
                if not dynamodb_running:
                    compose("start", "dynamodb")
                    wait_for(lambda: resource.meta.client.list_tables(), "DynamoDB cleanup restart")
                for item in produced:
                    key = {"intersection_id": intersection,
                           "window_key": f"{item['window_start']}#{item['window_id']}"}
                    summaries.store.table.delete_item(Key=key)
                    recommendations.store.table.delete_item(Key=key)


if __name__ == "__main__":
    unittest.main()
