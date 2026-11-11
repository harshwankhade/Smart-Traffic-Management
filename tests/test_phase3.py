"""Real loopback gRPC tests with injected sinks; real broker/store tested separately."""
import importlib.util
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "contracts/python", ROOT / "services/event-publisher", ROOT / "services/traffic-ingestion"):
    sys.path.insert(0, str(directory))

from traffic_contracts import publisher_pb2, publisher_pb2_grpc
from traffic_contracts.reading import Reading, archive_key
from publisher.adapters import Conflict, Unavailable
from publisher.service import Publisher
from ingestion.clients import RegistryClient, PublisherClient

SPEC = importlib.util.spec_from_file_location("ingestion_entry", ROOT / "services/traffic-ingestion/app.py")
INGESTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INGESTION)

SAMPLE = {"schema_version": "1.0", "event_id": "evt-test", "sensor_id": "sensor-01", "intersection_id": "int-01",
          "observed_at": "2026-11-09T10:00:00Z", "vehicle_count": 0, "average_speed": 18, "occupancy": 0.8}


class Archive:
    def __init__(self):
        self.records = {}
        self.failed = False

    def ensure(self, key, value):
        if self.failed:
            raise Unavailable("test archive failure")
        if key in self.records and self.records[key] != value:
            raise Conflict("test conflict")
        self.records[key] = value


class Sink:
    def __init__(self):
        self.records = []
        self.failed = False

    def publish(self, key, value):
        if self.failed:
            raise Unavailable("test broker failure")
        self.records.append((key, value))


class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.archive, self.sink = Archive(), Sink()
        self.registry_calls = []
        self.mode = "active"

        def registry(request):
            self.registry_calls.append(request)
            if self.mode == "timeout":
                raise httpx.ReadTimeout("test", request=request)
            if self.mode == "unknown":
                return httpx.Response(404)
            if self.mode == "unavailable":
                return httpx.Response(500)
            if self.mode == "malformed":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"sensor_id": "sensor-01", "intersection_id": "int-01", "status": self.mode})

        self.registry = RegistryClient("http://registry", transport=httpx.MockTransport(registry))
        self.start(Publisher(self.archive, self.sink))

    def start(self, service):
        server = grpc.server(ThreadPoolExecutor(max_workers=4))
        publisher_pb2_grpc.add_EventPublisherServicer_to_server(service, server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        self.addCleanup(lambda: server.stop(0).wait())
        publisher = PublisherClient(f"127.0.0.1:{port}")
        self.http = self.enterContext(TestClient(INGESTION.create_app(self.registry, publisher)))
        self.stub = publisher.stub

    def test_actual_rpc_canonical_payload_and_optional_zero(self):
        response = self.http.post("/readings", json=SAMPLE)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json(), {"event_id": "evt-test", "accepted": True})
        data = json.loads(self.archive.records[archive_key("evt-test")])
        self.assertEqual(data["vehicle_count"], 0)
        self.assertEqual(data["observed_at"], "2026-11-09T10:00:00.000000Z")
        self.assertEqual(self.sink.records, [("int-01", Reading(**SAMPLE).canonical())])
        single = {key: value for key, value in SAMPLE.items() if key not in ("average_speed", "occupancy")}
        wire = Reading(**single).to_proto()
        self.assertTrue(wire.HasField("vehicle_count"))
        self.assertFalse(wire.HasField("occupancy"))
        self.assertEqual(Reading.from_proto(wire).model_dump(exclude_none=True)["vehicle_count"], 0)

    def test_invalid_measurements_never_reach_registry_or_sinks(self):
        invalid = [("vehicle_count", True), ("vehicle_count", 1.5), ("vehicle_count", 2**63),
                   ("vehicle_count", -1), ("occupancy", None), ("occupancy", 1.01),
                   ("average_speed", "18"), ("event_id", " "), ("observed_at", "yesterday"),
                   ("observed_at", "2026-11-09T10:00:00+00:00"), ("extra", "field")]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                self.assertEqual(self.http.post("/readings", json={**SAMPLE, key: value}).status_code, 422)
        for value in ("NaN", "Infinity", "-Infinity"):
            raw = json.dumps(SAMPLE).replace('"average_speed": 18', f'"average_speed": {value}')
            self.assertEqual(self.http.post("/readings", content=raw, headers={"content-type": "application/json"}).status_code, 422)
        no_measurements = {key: value for key, value in SAMPLE.items() if key not in ("vehicle_count", "average_speed", "occupancy")}
        self.assertEqual(self.http.post("/readings", json=no_measurements).status_code, 422)
        self.assertEqual(self.registry_calls, [])
        self.assertFalse(self.archive.records)
        self.assertFalse(self.sink.records)

    def test_invalid_registry_references_and_failure_have_no_side_effect(self):
        for mode, expected in (("inactive", 422), ("unknown", 422), ("timeout", 503), ("unavailable", 503), ("malformed", 503)):
            with self.subTest(mode=mode):
                self.mode = mode
                before = len(self.registry_calls)
                response = self.http.post("/readings", json=SAMPLE)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.json()["event_id"], "evt-test")
                self.assertEqual(len(self.registry_calls), before + 1)
                self.assertEqual(self.registry_calls[-1].extensions["timeout"]["read"], 2)
        self.mode = "active"
        self.assertEqual(self.http.post("/readings", json={**SAMPLE, "intersection_id": "wrong"}).status_code, 422)
        self.assertFalse(self.archive.records)
        self.assertFalse(self.sink.records)

    def test_same_content_retry_and_conflicting_content(self):
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 202)
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 202)
        self.assertEqual(len(self.archive.records), 1)
        self.assertEqual(len(self.sink.records), 2)  # Deliberately honest at-least-once behavior.
        response = self.http.post("/readings", json={**SAMPLE, "vehicle_count": 5})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.sink.records), 2)

    def test_archive_and_broker_failures_recover_on_same_id(self):
        self.archive.failed = True
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 503)
        self.assertFalse(self.sink.records)
        self.archive.failed = False
        self.sink.failed = True
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 503)
        self.assertEqual(len(self.archive.records), 1)
        self.assertFalse(self.sink.records)
        self.sink.failed = False
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 202)

    def test_direct_rpc_revalidation(self):
        with self.assertRaises(grpc.RpcError) as caught:
            self.stub.PublishReading(publisher_pb2.ReadingEvent(), timeout=3)
        self.assertEqual(caught.exception.code(), grpc.StatusCode.INVALID_ARGUMENT)
        self.assertFalse(self.archive.records)

    def test_timestamp_canonicalization_preserves_precision(self):
        a = Reading(**{**SAMPLE, "observed_at": "2026-11-09T10:00:00.123456700Z"})
        b = Reading(**{**SAMPLE, "observed_at": "2026-11-09T10:00:00.1234567Z"})
        self.assertEqual(a.canonical(), b.canonical())
        self.assertEqual(a.observed_at, "2026-11-09T10:00:00.1234567Z")
        with self.assertRaises(ValidationError):
            Reading(**{**SAMPLE, "observed_at": "2026-11-09T10:00:00,123Z"})

    def test_concurrent_conflicting_calls_preserve_first_archive(self):
        messages = [Reading(**{**SAMPLE, "vehicle_count": value}).to_proto() for value in range(4)]
        def send(message):
            try:
                return self.stub.PublishReading(message, timeout=5).accepted
            except grpc.RpcError as error:
                return error.code()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(send, messages))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(grpc.StatusCode.ALREADY_EXISTS), 3)
        self.assertEqual(len(self.archive.records), 1)

    def test_controlled_lost_acknowledgement(self):
        class LostAck(Publisher):
            lost = False
            def PublishReading(inner, request, context):
                receipt = super(LostAck, inner).PublishReading(request, context)
                if not inner.lost:
                    inner.lost = True
                    context.abort(grpc.StatusCode.UNAVAILABLE, "Test: committed result, lost response")
                return receipt
        self.start(LostAck(self.archive, self.sink))
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 503)
        self.assertEqual(len(self.sink.records), 1)
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 202)
        self.assertEqual(len(self.archive.records), 1)
        self.assertEqual(len(self.sink.records), 2)

    def test_deadline_mapping_and_deterministic_generator(self):
        class Deadline(publisher_pb2_grpc.EventPublisherServicer):
            calls = 0
            remaining = None
            def PublishReading(inner, request, context):
                inner.calls += 1
                inner.remaining = context.time_remaining()
                context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "test deadline")
        service = Deadline()
        self.start(service)
        self.assertEqual(self.http.post("/readings", json=SAMPLE).status_code, 503)
        self.assertEqual(service.calls, 1)
        self.assertGreater(service.remaining, 13)
        self.assertLessEqual(service.remaining, 15.1)
        spec = importlib.util.spec_from_file_location("generator", ROOT / "scripts/generate_readings.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual(generator.generate(5, 12), generator.generate(5, 12))
        self.assertNotEqual(generator.generate(5, 12), generator.generate(5, 13))


if __name__ == "__main__":
    unittest.main()
