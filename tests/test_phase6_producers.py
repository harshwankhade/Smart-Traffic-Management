"""Focused producer and transactional outbox checks; no cloud dependencies."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
for path in ("contracts/python", "services/incident-manager", "services/signal-recommendation"):
    sys.path.insert(0, str(ROOT / path))

from incidents.database import Database  # noqa: E402
from incidents.models import AlertOutboxRow, IncidentRow  # noqa: E402
from incidents.outbox import claim_one, deliver_one  # noqa: E402
from incidents import repository as repo  # noqa: E402
from traffic_contracts.alerts import InMemoryAlertSender, congestion_request  # noqa: E402
from tests.test_phase5_storage import result  # noqa: E402


def load_signal_app():
    spec = importlib.util.spec_from_file_location("phase6_signal_app", ROOT / "services/signal-recommendation/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = "sqlite:///" + (Path(self.temp.name) / "incidents.db").as_posix()
        self.db = Database(self.url)
        self.db.initialize()
        self.addCleanup(self.db.engine.dispose)

    def rows(self):
        with self.db.sessions() as session:
            return session.scalars(select(AlertOutboxRow).order_by(AlertOutboxRow.created_at)).all()

    def create(self):
        with self.db.sessions() as session:
            return repo.create(session, {"incident_id": "inc-1", "intersection_id": "int-1",
                                         "type": "closure", "description": "closed"})

    def test_contract_and_high_only_stable(self):
        schema = json.loads((ROOT / "contracts/v1/alert.schema.json").read_text())
        value = result("int-1", 0)
        value["congestion"] = "high"
        value["average_speed"] = 10
        request = congestion_request(value)
        self.assertEqual(request, congestion_request(value))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(request)
        self.assertIsNone(congestion_request({**value, "congestion": "low"}))

    def test_signal_persists_then_sends_and_retries_same_request(self):
        signal = load_signal_app()
        sender = InMemoryAlertSender()
        calls = []

        class Repository:
            store = object()

            def put(self, record):
                calls.append(record)
                return "unchanged" if len(calls) > 1 else "created"

        class Worker:
            def __init__(self, group, store, persist):
                self.persist = persist

            def start(self):
                pass

            def stop(self):
                pass

        value = result("int-1", 0)
        value["congestion"] = "high"
        value["average_speed"] = 10
        with patch.dict(os.environ, {"PHASE5_CONSUMER_ENABLED": "1"}), patch.object(signal, "ResultConsumer", Worker):
            app = signal.create_app(repository=Repository(), alert_sender=sender)
            with TestClient(app):
                sender.available = False
                with self.assertRaises(ConnectionError):
                    app.state.worker.persist(value)
                sender.available = True
                self.assertEqual(app.state.worker.persist(value), "unchanged")
                self.assertEqual(json.loads(sender.messages[0]), congestion_request(value))
                self.assertEqual(len(calls), 2)
                app.state.worker.persist({**value, "congestion": "low", "average_speed": 50,
                                          "average_occupancy": 0.2})
                self.assertEqual(len(sender.messages), 1)

    def test_incident_create_status_and_description_only(self):
        original = self.create()
        self.assertEqual(len(self.rows()), 1)
        first = json.loads(self.rows()[0].request_json)
        self.assertEqual(first["source_id"], original.event_id)
        with self.db.sessions() as session:
            row = session.get(IncidentRow, "inc-1")
            repo.update(session, row, {"description": "new text"})
            self.assertEqual(len(self.rows()), 1)
            repo.update(session, row, {"status": "resolved"})
            repo.update(session, row, {"status": "resolved"})
        self.assertEqual(len(self.rows()), 2)

    def test_queue_outage_restart_and_duplicate_ack(self):
        self.create()
        sender = InMemoryAlertSender()
        sender.available = False
        self.assertFalse(deliver_one(self.db, sender))
        self.assertEqual(self.rows()[0].attempt_count, 1)
        self.assertIsNone(self.rows()[0].sent_at)
        sender.available = True
        restarted = Database(self.url)
        self.addCleanup(restarted.engine.dispose)
        self.assertTrue(deliver_one(restarted, sender, now=datetime.now(UTC) + timedelta(seconds=3)))
        self.assertIsNotNone(self.rows()[0].sent_at)
        self.assertFalse(deliver_one(restarted, sender))
        self.assertEqual(len(sender.messages), 1)

    def test_ambiguous_send_and_expired_lease(self):
        self.create()
        sender = InMemoryAlertSender()
        with self.db.sessions() as session:
            claimed = claim_one(session, lease_seconds=1)
        self.assertIsNotNone(claimed)
        self.assertFalse(deliver_one(self.db, sender))
        self.assertTrue(deliver_one(self.db, sender, now=datetime.now(UTC) + timedelta(seconds=2)))
        self.assertEqual(len(sender.messages), 1)

    def test_ambiguous_ack_retries_identical_body(self):
        self.create()
        sender = InMemoryAlertSender()
        original_send = sender.send

        def accepted_without_ack(request):
            original_send(request)
            raise TimeoutError("ack lost")

        sender.send = accepted_without_ack
        self.assertFalse(deliver_one(self.db, sender))
        sender.send = original_send
        self.assertTrue(deliver_one(self.db, sender, now=datetime.now(UTC) + timedelta(seconds=3)))
        self.assertEqual(sender.messages[0], sender.messages[1])
        self.assertEqual(self.rows()[0].attempt_count, 2)

    def test_transaction_rollback_keeps_incident_and_outbox_absent(self):
        with self.db.sessions() as session, patch.object(repo, "queue_alert", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                repo.create(session, {"incident_id": "inc-1", "intersection_id": "int-1",
                                      "type": "closure", "description": "closed"})
            session.rollback()
        with self.db.sessions() as session:
            self.assertIsNone(session.get(IncidentRow, "inc-1"))
        self.assertFalse(self.rows())


if __name__ == "__main__":
    unittest.main()
