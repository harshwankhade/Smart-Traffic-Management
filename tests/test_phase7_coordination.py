import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/event-publisher"))
sys.path.insert(0, str(ROOT / "contracts/python"))

from publisher.coordination import SinglePublisher, ZooKeeperElection
from publisher.service import Publisher
from traffic_contracts.reading import Reading
sys.path.insert(0, str(ROOT / "services/traffic-ingestion"))
from ingestion.clients import ZooKeeperPublisherClient


class Backend:
    def __init__(self):
        self.nodes, self.clients, self.watches, self.sequence = {}, [], {}, 0


class Client:
    def __init__(self, backend):
        self.backend, self.listener, self.nodes = backend, None, []
        backend.clients.append(self)

    def add_listener(self, listener): self.listener = listener
    def start(self, timeout): self.listener("CONNECTED")
    def ensure_path(self, path): pass
    def create(self, prefix, value, ephemeral, sequence):
        self.backend.sequence += 1
        path = f"{prefix}{self.backend.sequence:010d}"
        self.backend.nodes[path] = self
        self.nodes.append(path)
        return path
    def get_children(self, root): return [path.rsplit("/", 1)[1] for path in self.backend.nodes if path.startswith(root + "/")]
    def exists(self, path, watch=None):
        if watch: self.backend.watches.setdefault(path, []).append(watch)
        return path in self.backend.nodes
    def stop(self): pass
    def close(self):
        for path in self.nodes:
            self.backend.nodes.pop(path, None)
            for watch in self.backend.watches.pop(path, []): watch(None)
        self.nodes = []


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.factory = lambda _: Client(self.backend)

    def test_ephemeral_sequential_leader_and_predecessor_takeover(self):
        first = ZooKeeperElection(instance_id="a", client_factory=self.factory)
        second = ZooKeeperElection(instance_id="b", client_factory=self.factory)
        first.start(); second.start()
        self.assertTrue(first.ready())
        self.assertFalse(second.ready())
        self.assertEqual(second.status()["leader"], False)
        first_node = first.status()["node"]
        first.stop()
        self.assertTrue(second.ready())
        restarted = ZooKeeperElection(instance_id="a", client_factory=self.factory)
        restarted.start()
        self.assertFalse(restarted.ready())
        self.assertNotEqual(restarted.status()["node"], first_node)
        second.stop()
        self.assertTrue(restarted.ready())
        restarted.stop()

    def test_session_suspension_fails_closed_and_single_mode_is_compatible(self):
        election = ZooKeeperElection(instance_id="a", client_factory=self.factory)
        election.start()
        election._on_state("SUSPENDED")
        self.assertFalse(election.ready())
        election.stop()
        legacy = SinglePublisher()
        legacy.start()
        self.assertTrue(legacy.ready())
        self.assertEqual(legacy.status()["enabled"], False)

    def test_follower_rejects_publication_before_archive_or_kafka(self):
        class Follower:
            def ready(self): return False

        class Archive:
            def ensure(self, *_): self.called = True

        class Sink:
            def publish(self, *_): self.called = True

        class Context:
            def time_remaining(self): return 15
            def abort(self, code, detail): raise RuntimeError((code, detail))

        archive, sink = Archive(), Sink()
        reading = Reading(schema_version="1.0", event_id="phase7-follower", sensor_id="sensor-01",
                          intersection_id="int-01", observed_at="2026-11-09T10:00:00Z", vehicle_count=1)
        with self.assertRaises(RuntimeError) as rejected:
            Publisher(archive, sink, Follower()).PublishReading(reading.to_proto(), Context())
        self.assertIn("not the active ZooKeeper leader", rejected.exception.args[0][1])
        self.assertFalse(hasattr(archive, "called"))
        self.assertFalse(hasattr(sink, "called"))

    def test_ingestion_rediscovers_successor_and_retries_same_event_id(self):
        calls, closed = [], []

        class Discovery:
            def __init__(self): self.values = [("leader:50051", "http://leader"), ("successor:50052", "http://successor")]
            def start(self, timeout): pass
            def get_children(self, root): return ["publisher-0000000001"]
            def get(self, path):
                target, health = self.values.pop(0)
                return json.dumps({"grpc_target": target, "http_url": health}).encode(), None
            def stop(self): pass
            def close(self): pass

        class PublisherStub:
            def __init__(self, target, health): self.target, self.health = target, health
            def publish(self, reading):
                calls.append((self.target, reading.event_id))
                if self.target == "leader:50051":
                    from fastapi import HTTPException
                    raise HTTPException(503, "leader changed")
            def ready(self): pass
            def close(self): closed.append(self.target)

        client = ZooKeeperPublisherClient(client_factory=lambda _: Discovery(), publisher_factory=PublisherStub,
                                          attempts=2, delay_seconds=0, sleeper=lambda _: None)
        reading = Reading(schema_version="1.0", event_id="same-id", sensor_id="sensor-01",
                          intersection_id="int-01", observed_at="2026-11-09T10:00:00Z", vehicle_count=1)
        client.publish(reading)
        self.assertEqual(calls, [("leader:50051", "same-id"), ("successor:50052", "same-id")])
        self.assertEqual(closed, ["leader:50051", "successor:50052"])
        client.close()

    def test_recovery_reporting_records_events_and_counts_failures(self):
        class Reporter:
            def __init__(self): self.events = []
            def report(self, event): self.events.append(event)

        reporter = Reporter()
        election = ZooKeeperElection(instance_id="publisher-a", client_factory=self.factory, reporter=reporter)
        election.start()
        election._on_state("SUSPENDED")
        self.assertEqual([event["event_type"] for event in reporter.events],
                         ["leader_elected", "leader_lost", "session_suspended"])
        self.assertEqual(election.status()["metrics"]["leader_transitions"], 1)
        self.assertEqual(election.status()["metrics"]["report_failures"], 0)
        election.stop()

        class FailingReporter:
            def report(self, event): raise RuntimeError("storage unavailable")

        failed = ZooKeeperElection(instance_id="publisher-b", client_factory=self.factory, reporter=FailingReporter())
        failed.start()
        self.assertEqual(failed.status()["metrics"]["report_failures"], 1)
        failed.stop()

