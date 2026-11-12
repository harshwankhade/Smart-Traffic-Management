"""Real local ZooKeeper publisher-failover demonstration for Phase 7.

Runs only loopback Docker dependencies and temporary Python service processes. It retains
existing Docker volumes and does not create AWS resources.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import grpc
import httpx
from botocore.exceptions import ClientError
from fastapi import HTTPException

from demo_phase2 import LocalService
from phase3_local import ROOT, bootstrap as phase3_bootstrap, compose as phase3_compose, local_environment
from phase5_local import bootstrap as phase5_bootstrap, compose as phase5_compose
from inspect_phase3 import consume

sys.path.insert(0, str(ROOT / "contracts/python"))
sys.path.insert(0, str(ROOT / "services/event-publisher"))
sys.path.insert(0, str(ROOT / "services/traffic-ingestion"))
from publisher.adapters import S3Archive
from traffic_contracts import publisher_pb2_grpc
from traffic_contracts.reading import Reading, archive_key
from ingestion.clients import PublisherClient


PHASE7_COMPOSE = ROOT / "infrastructure/local/phase7/compose.yaml"


def phase7_compose(*arguments):
    subprocess.run(["docker", "compose", "-f", str(PHASE7_COMPOSE), *arguments], cwd=ROOT, check=True)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(action, description, seconds=35):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            value = action()
            if value:
                return value
        except Exception as error:
            last = error
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {description}: {last}")


def run(report=None):
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    environment = local_environment()
    os.environ.update(environment)
    phase3_compose("up", "-d")
    phase5_compose("up", "-d")
    phase7_compose("up", "-d")
    phase3_bootstrap()
    phase5_bootstrap()
    archive = S3Archive()
    services, proxy_server, proxy_channel = [], None, None
    with tempfile.TemporaryDirectory(prefix="traffic-phase7-demo-") as temporary, httpx.Client(timeout=5, trust_env=False) as http:
        def start(name, env, port=0):
            service = LocalService(name, temporary, env, port=port).start()
            services.append(service)
            return service

        def coordination(service):
            response = http.get(service.base + "/coordination")
            if response.status_code != 200:
                raise RuntimeError(response.text)
            return response.json()

        def leader_of(candidates):
            for candidate in candidates:
                try:
                    if coordination(candidate)["leader"] and http.get(candidate.base + "/readyz").status_code == 200:
                        return candidate
                except httpx.HTTPError:
                    pass
            return None

        def post(reading, expected=202):
            response = http.post(ingestion.base + "/readings", json=reading)
            if response.status_code != expected:
                raise AssertionError(f"Expected {expected}, got {response.status_code}: {response.text}")
            return response

        def absent(event_id):
            try:
                archive.read(archive_key(event_id))
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
                    raise
            else:
                raise AssertionError(f"Rejected new request {event_id} reached the archive")

        try:
            analytics = start("traffic-analytics", {**environment, "DYNAMODB_ENDPOINT_URL": "http://127.0.0.1:8000"})
            registry = start("sensor-registry", {**environment,
                              "SENSOR_REGISTRY_DATABASE_URL": f"sqlite:///{(Path(temporary) / 'registry.db').as_posix()}"})
            publisher_ports = [(free_port(), free_port()), (free_port(), free_port())]
            election_root = "/smarttraffic/phase7-" + uuid4().hex[:12] + "/publishers"

            def publisher_env(name, ports):
                http_port, grpc_port = ports
                return {**environment, "PUBLISHER_ZOOKEEPER_ENABLED": "1",
                        "PUBLISHER_ZOOKEEPER_HOSTS": "127.0.0.1:2181", "PUBLISHER_INSTANCE_ID": name,
                        "PUBLISHER_ZOOKEEPER_ROOT": election_root,
                        "PUBLISHER_GRPC_BIND": f"127.0.0.1:{grpc_port}",
                        "PUBLISHER_ADVERTISED_GRPC_TARGET": f"127.0.0.1:{grpc_port}",
                        "PUBLISHER_ADVERTISED_HTTP_URL": f"http://127.0.0.1:{http_port}",
                        "RECOVERY_EVENTS_ENABLED": "1", "TRAFFIC_ANALYTICS_URL": analytics.base}

            first = start("event-publisher", publisher_env("publisher-a", publisher_ports[0]), publisher_ports[0][0])
            second = start("event-publisher", publisher_env("publisher-b", publisher_ports[1]), publisher_ports[1][0])
            publishers = [first, second]
            initial_leader = wait_for(lambda: leader_of(publishers), "initial ZooKeeper leader")
            initial_follower = second if initial_leader is first else first
            initial_leader_id = coordination(initial_leader)["instance_id"]
            initial_node = coordination(initial_leader)["node"]

            ingestion = start("traffic-ingestion", {**environment, "SENSOR_REGISTRY_URL": registry.base,
                              "PUBLISHER_ZOOKEEPER_ENABLED": "1", "PUBLISHER_ZOOKEEPER_HOSTS": "127.0.0.1:2181",
                              "PUBLISHER_ZOOKEEPER_ROOT": election_root,
                              "PUBLISHER_FAILOVER_RETRY_ATTEMPTS": "3", "PUBLISHER_FAILOVER_RETRY_DELAY_SECONDS": "0.15"})
            prefix = "p7-" + uuid4().hex[:12]
            intersection, sensor = f"int-{prefix}", f"sensor-{prefix}"
            assert http.post(registry.base + "/intersections", json={"intersection_id": intersection, "name": "Phase 7", "location": "Demo"}).status_code == 201
            assert http.post(registry.base + "/sensors", json={"sensor_id": sensor, "intersection_id": intersection, "location": "Lane 1", "status": "active"}).status_code == 201

            def reading(label):
                return {"schema_version": "1.0", "event_id": f"{prefix}-{label}", "sensor_id": sensor,
                        "intersection_id": intersection, "observed_at": "2026-11-12T10:00:00Z", "vehicle_count": 3}

            before = reading("before-crash")
            post(before)
            rejected = reading("follower-new-request")
            follower_status = coordination(initial_follower)
            direct_follower = PublisherClient(follower_status["grpc_target"], initial_follower.base)
            try:
                with __import__("contextlib").suppress(HTTPException):
                    direct_follower.publish(Reading(**rejected))
                    raise AssertionError("Nonleader accepted a new request")
            finally:
                direct_follower.close()
            absent(rejected["event_id"])

            # Forward to the real leader then deliberately lose one successful acknowledgement.
            leader_status = coordination(initial_leader)
            proxy_channel = grpc.insecure_channel(leader_status["grpc_target"])
            target = publisher_pb2_grpc.EventPublisherStub(proxy_channel)

            class LostAcknowledgement(publisher_pb2_grpc.EventPublisherServicer):
                used = False
                def PublishReading(self, request, context):
                    result = target.PublishReading(request, timeout=15)
                    if not self.used:
                        self.used = True
                        context.abort(grpc.StatusCode.UNAVAILABLE, "deliberately lost acknowledgement")
                    return result

            proxy_server = grpc.server(ThreadPoolExecutor(max_workers=2))
            publisher_pb2_grpc.add_EventPublisherServicer_to_server(LostAcknowledgement(), proxy_server)
            proxy_port = proxy_server.add_insecure_port("127.0.0.1:0")
            proxy_server.start()
            ambiguous = reading("ambiguous-ack")
            proxy = PublisherClient(f"127.0.0.1:{proxy_port}")
            try:
                with __import__("contextlib").suppress(HTTPException):
                    proxy.publish(Reading(**ambiguous))
                    raise AssertionError("Lost acknowledgement was not surfaced")
            finally:
                proxy.close()
            assert archive.read(archive_key(ambiguous["event_id"])) == Reading(**ambiguous).canonical()
            post(ambiguous)  # Same ID is safe to retry; Kafka remains at-least-once.
            proxy_server.stop(0).wait(); proxy_server = None
            proxy_channel.close(); proxy_channel = None

            # Terminate the elected process: successor must become ready and resume publication.
            initial_leader.stop()
            surviving = initial_follower
            successor = wait_for(lambda: leader_of([surviving]), "successor election")
            after_crash = reading("after-crash")
            post(after_crash)

            # Restart the former leader with the same logical ID. Its fresh node remains a follower.
            restarted = start("event-publisher", publisher_env("publisher-a" if initial_leader is first else "publisher-b",
                              publisher_ports[0] if initial_leader is first else publisher_ports[1]),
                              publisher_ports[0][0] if initial_leader is first else publisher_ports[1][0])
            restarted_status = wait_for(lambda: coordination(restarted), "restarted publisher registration")
            if restarted_status["leader"] or restarted_status["node"] == initial_node:
                raise AssertionError("Restarted former leader restored its old leadership state")

            # Keep ZooKeeper transaction history; stop long enough to expire client sessions.
            phase7_compose("stop", "zookeeper")
            wait_for(lambda: http.get(successor.base + "/readyz").status_code == 503,
                     "publisher fail-closed readiness", seconds=15)
            suspended = reading("session-unavailable")
            post(suspended, 503)
            absent(suspended["event_id"])
            time.sleep(6)
            phase7_compose("start", "zookeeper")
            active = wait_for(lambda: leader_of([successor, restarted]), "fresh-session re-election", seconds=45)
            def session_lost_recorded():
                for publisher_id in ("publisher-a", "publisher-b"):
                    response = http.get(analytics.base + "/traffic/recovery-events",
                                        params={"publisher_id": publisher_id, "from": started_at, "limit": 100})
                    if response.status_code == 200 and any(item["event_type"] == "session_lost"
                                                           for item in response.json()["items"]):
                        return True
                return False
            wait_for(session_lost_recorded, "fresh-session recovery record", seconds=15)
            after_session = reading("after-session-recovery")
            post(after_session)

            records = [item for item in consume(5) if item["record"].get("event_id", "").startswith(prefix)]
            counts = Counter(item["record"]["event_id"] for item in records)
            for item in (before, ambiguous, after_crash, after_session):
                if counts[item["event_id"]] < 1:
                    raise AssertionError(f"Accepted event absent from Kafka: {item['event_id']}")
            if counts[ambiguous["event_id"]] < 2:
                raise AssertionError("Ambiguous acknowledgement retry did not preserve at-least-once evidence")
            if counts[rejected["event_id"]] or counts[suspended["event_id"]]:
                raise AssertionError("Rejected new request reached Kafka")

            recovery = {}
            for publisher_id in ("publisher-a", "publisher-b"):
                response = http.get(analytics.base + "/traffic/recovery-events",
                                    params={"publisher_id": publisher_id, "from": started_at, "limit": 100})
                if response.status_code != 200:
                    raise AssertionError(response.text)
                recovery[publisher_id] = response.json()["items"]
            event_types = {item["event_type"] for items in recovery.values() for item in items}
            if not {"leader_elected", "leader_lost", "session_lost", "session_rejoined"}.issubset(event_types):
                raise AssertionError(f"Recovery evidence incomplete: {sorted(event_types)}")

            result = {"run_prefix": prefix, "scope": "local_only", "started_at": started_at,
                      "initial_leader": initial_leader_id,
                      "post_session_leader": coordination(active)["instance_id"], "kafka_counts": dict(counts),
                      "rejected_new_requests": [rejected["event_id"], suspended["event_id"]],
                      "recovery_event_types": sorted(event_types),
                      "limitations": ["Delayed in-flight Kafka writes are not fenced by ZooKeeper readiness/session checks.",
                                      "Kafka output is at least once; the lost-acknowledgement retry intentionally produced duplicate records.",
                                      "This local crash/session test does not prove partition-safe exclusive publishing or zero loss."]}
            print(json.dumps(result, indent=2))
            if report:
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        finally:
            if sys.exc_info()[0] and report:
                diagnostics = {"error": str(sys.exc_info()[1]), "services": {}}
                for service in services:
                    entry = {"pid": service.process.pid, "exit_code": service.process.poll()}
                    if service.name == "event-publisher":
                        try:
                            entry["coordination"] = coordination(service)
                        except Exception as error:
                            entry["coordination_error"] = str(error)
                    if not service.log.closed:
                        service.log.flush()
                    entry["log_tail"] = Path(service.log.name).read_text(encoding="utf-8", errors="replace")[-4000:]
                    diagnostics["services"][f"{service.name}-{service.process.pid}"] = entry
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text(json.dumps({"status": "failed", **diagnostics}, indent=2) + "\n", encoding="utf-8")
            for service in reversed(services):
                service.stop()
            if proxy_server:
                proxy_server.stop(0).wait()
            if proxy_channel:
                proxy_channel.close()
            archive.close()
    print("PASS Phase 7 local services stopped; Docker containers and volumes retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write credential-free observed results after all checks pass")
    args = parser.parse_args()
    try:
        run(args.report)
    except BaseException as error:
        if args.report and not args.report.exists():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"status": "failed", "error": str(error)}, indent=2) + "\n",
                                   encoding="utf-8")
        raise
