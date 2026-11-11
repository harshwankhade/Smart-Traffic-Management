"""Verify the actual HTTP -> gRPC -> Kafka + persistent S3-compatible path."""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import grpc
import httpx
from botocore.exceptions import ClientError
from jsonschema import Draft202012Validator, FormatChecker

from phase3_local import ROOT, bootstrap, compose, local_environment
from demo_phase2 import LocalService
from generate_readings import generate
from inspect_phase3 import consume
from publisher.adapters import S3Archive
from traffic_contracts import publisher_pb2_grpc
from traffic_contracts.reading import Reading, archive_key


def run(failure_tests=False, report=None):
    env = local_environment()
    os.environ.update(env)
    bootstrap()
    archive = S3Archive()
    services = []
    restarted_containers = set()
    with tempfile.TemporaryDirectory(prefix="traffic-phase3-demo-") as temp, httpx.Client(timeout=25, trust_env=False) as http:
        env.update({"SENSOR_REGISTRY_DATABASE_URL": f"sqlite:///{temp.replace(chr(92), '/')}/registry.db",
                    "PUBLISHER_GRPC_BIND": "127.0.0.1:0"})
        registry = LocalService("sensor-registry", temp, env)
        publisher = LocalService("event-publisher", temp, env)
        ingestion = None
        proxy_server = None
        proxy_channel = None

        def start_ingestion(target=None):
            nonlocal ingestion
            if ingestion:
                ingestion.stop()
            settings = {**env, "SENSOR_REGISTRY_URL": registry.base, "PUBLISHER_HTTP_URL": publisher.base,
                        "PUBLISHER_GRPC_TARGET": target or f"127.0.0.1:{wait_ready(publisher)['grpc_port']}"}
            ingestion = LocalService("traffic-ingestion", temp, settings).start()
            services.append(ingestion)

        def wait_ready(service):
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    response = http.get(service.base + "/readyz")
                    if response.status_code == 200:
                        return response.json()
                except httpx.HTTPError:
                    pass
                time.sleep(0.3)
            raise RuntimeError(f"{service.name} dependencies not ready")

        def submit(reading, expected=202):
            response = http.post(ingestion.base + "/readings", json=reading)
            if response.status_code != expected:
                raise AssertionError(f"Expected {expected}, got {response.status_code}: {response.text}")
            assert response.json().get("event_id") == reading["event_id"]
            if expected == 202:
                assert response.json()["accepted"] is True
            return response

        def assert_absent(event_id):
            try:
                archive.read(archive_key(event_id))
            except ClientError as error:
                assert error.response["Error"]["Code"] in ("NoSuchKey", "404"), str(error)
            else:
                raise AssertionError(f"Rejected event {event_id} was archived")

        try:
            registry.start()
            publisher.start()
            start_ingestion()
            wait_ready(ingestion)
            prefix = f"run-{uuid4().hex[:12]}"
            intersection, sensor = f"int-{prefix}", f"sensor-{prefix}"
            assert http.post(registry.base + "/intersections", json={"intersection_id": intersection, "name": "Phase 3", "location": "Demo"}).status_code == 201
            assert http.post(registry.base + "/sensors", json={"sensor_id": sensor, "intersection_id": intersection, "location": "Lane 1", "status": "active"}).status_code == 201
            reading = generate(1, sensor_id=sensor, intersection_id=intersection, prefix=prefix)[0]
            accepted = {reading["event_id"]: Reading(**reading).canonical()}
            rejected = []
            submit(reading)
            assert archive.read(archive_key(reading["event_id"])) == accepted[reading["event_id"]]
            submit(reading)
            submit({**reading, "vehicle_count": reading["vehicle_count"] + 1}, 409)
            for suffix, change in (("negative", {"vehicle_count": -1}), ("unknown", {"sensor_id": "absent"}),
                                   ("mismatch", {"intersection_id": "wrong"})):
                invalid = {**reading, "event_id": f"{prefix}-{suffix}", **change}
                submit(invalid, 422)
                rejected.append(invalid["event_id"])
                assert_absent(invalid["event_id"])
            assert http.patch(registry.base + f"/sensors/{sensor}", json={"status": "inactive"}).status_code == 200
            inactive = {**reading, "event_id": f"{prefix}-inactive"}
            submit(inactive, 422)
            rejected.append(inactive["event_id"])
            assert_absent(inactive["event_id"])
            http.patch(registry.base + f"/sensors/{sensor}", json={"status": "active"})

            same = {**reading, "event_id": f"{prefix}-concurrent"}
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: submit(same), range(4)))
            accepted[same["event_id"]] = Reading(**same).canonical()
            conflict_id = f"{prefix}-concurrent-conflict"
            competing = [{**reading, "event_id": conflict_id, "vehicle_count": value} for value in range(3)]
            with ThreadPoolExecutor(max_workers=3) as pool:
                responses = list(pool.map(lambda item: http.post(ingestion.base + "/readings", json=item), competing))
            assert [response.status_code for response in responses].count(202) == 1
            assert [response.status_code for response in responses].count(409) == 2
            winner = next(item for item, response in zip(competing, responses) if response.status_code == 202)
            accepted[conflict_id] = Reading(**winner).canonical()
            assert archive.read(archive_key(conflict_id)) == accepted[conflict_id]
            publisher.stop()
            publisher.start()
            start_ingestion()
            submit(same)
            assert archive.read(archive_key(same["event_id"])) == accepted[same["event_id"]]
            print("PASS real REST/gRPC, Kafka/archive acknowledgement, invalid-reference rejection, retries and publisher restart")

            # A loopback test proxy forwards to the real Publisher, then drops one successful response.
            target = f"127.0.0.1:{wait_ready(publisher)['grpc_port']}"
            proxy_channel = grpc.insecure_channel(target)
            real_stub = publisher_pb2_grpc.EventPublisherStub(proxy_channel)
            class LostAck(publisher_pb2_grpc.EventPublisherServicer):
                lost = False
                def PublishReading(inner, request, context):
                    result = real_stub.PublishReading(request, timeout=15)
                    if not inner.lost:
                        inner.lost = True
                        context.abort(grpc.StatusCode.UNAVAILABLE, "Test proxy deliberately lost the acknowledgement")
                    return result
            proxy_server = grpc.server(ThreadPoolExecutor(max_workers=2))
            publisher_pb2_grpc.add_EventPublisherServicer_to_server(LostAck(), proxy_server)
            proxy_port = proxy_server.add_insecure_port("127.0.0.1:0")
            proxy_server.start()
            start_ingestion(f"127.0.0.1:{proxy_port}")
            uncertain = {**reading, "event_id": f"{prefix}-lost-ack"}
            submit(uncertain, 503)
            assert archive.read(archive_key(uncertain["event_id"])) == Reading(**uncertain).canonical()
            submit(uncertain)
            accepted[uncertain["event_id"]] = Reading(**uncertain).canonical()
            start_ingestion()
            print("PASS controlled lost acknowledgement: both real sinks committed; same-ID retry recovered")

            if failure_tests:
                registry.stop()
                unavailable = {**reading, "event_id": f"{prefix}-registry-outage"}
                submit(unavailable, 503)
                assert_absent(unavailable["event_id"])
                registry.start()
                start_ingestion()
                submit(unavailable)
                accepted[unavailable["event_id"]] = Reading(**unavailable).canonical()
                publisher.stop()
                unavailable = {**reading, "event_id": f"{prefix}-publisher-outage"}
                submit(unavailable, 503)
                assert_absent(unavailable["event_id"])
                publisher.start()
                start_ingestion()
                submit(unavailable)
                accepted[unavailable["event_id"]] = Reading(**unavailable).canonical()
                for container in ("archive", "kafka"):
                    compose("stop", container)
                    restarted_containers.add(container)
                    unavailable = {**reading, "event_id": f"{prefix}-{container}-outage"}
                    submit(unavailable, 503)
                    assert http.get(publisher.base + "/readyz").status_code == 503
                    if container == "kafka":
                        assert archive.read(archive_key(unavailable["event_id"])) == Reading(**unavailable).canonical()
                    compose("start", container)
                    restarted_containers.remove(container)
                    bootstrap()
                    wait_ready(publisher)
                    if container == "archive":
                        assert_absent(unavailable["event_id"])
                    submit(unavailable)
                    accepted[unavailable["event_id"]] = Reading(**unavailable).canonical()
                compose("restart")
                bootstrap()
                wait_ready(publisher)
                print("PASS real Registry/publisher/store/broker outages and container restart persistence")

            records = [item for item in consume(5) if item["record"]["event_id"].startswith(prefix)]
            counts = Counter(item["record"]["event_id"] for item in records)
            schema = json.loads((ROOT / "contracts/v1/reading.schema.json").read_text())
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            for item in records:
                event = item["record"]
                validator.validate(event)
                assert event["event_id"] in accepted, f"Rejected event reached Kafka: {event['event_id']}"
                assert item["key"] == intersection
                assert json.loads(accepted[event["event_id"]]) == event
            for event_id, payload in accepted.items():
                assert counts[event_id] >= 1, f"Accepted event absent from Kafka: {event_id}"
                assert archive.read(archive_key(event_id)) == payload
            for event_id in rejected:
                assert counts[event_id] == 0
                assert_absent(event_id)
            assert counts[uncertain["event_id"]] >= 2
            result = {"run_prefix": prefix, "logical_events": len(accepted), "kafka_records": len(records),
                      "duplicate_records": len(records) - len(accepted), "rejected_without_side_effects": len(rejected),
                      "concurrent_conflicting_attempts": {"accepted": 1, "conflicts": 2},
                      "failure_tests": failure_tests, "kafka_image": "apache/kafka:3.9.1",
                      "archive_image": "chrislusf/seaweedfs:4.42", "scope": "local_only"}
            print(json.dumps(result, indent=2))
            if report:
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print("PASS consumed actual Kafka records and retrieved matching durable archive objects")
        finally:
            for container in restarted_containers:
                compose("start", container)
            for service in reversed(services):
                service.stop()
            publisher.stop()
            registry.stop()
            if proxy_server:
                proxy_server.stop(0).wait()
            if proxy_channel:
                proxy_channel.close()
            archive.close()
    print("PASS service processes stopped; local dependency containers and persistent volumes retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure-tests", action="store_true", help="Stop/restart only this project's local dependency containers")
    parser.add_argument("--report", type=Path, help="Write a credential-free verification summary after all data checks pass")
    args = parser.parse_args()
    run(args.failure_tests, args.report)
