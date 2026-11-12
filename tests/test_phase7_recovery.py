import importlib.util
import sys
import unittest
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts/python"))
sys.path.insert(0, str(ROOT / "services/traffic-analytics"))

from analytics.recovery_repository import RecoveryConflict
from traffic_contracts.recovery import validate_recovery_event

SPEC = importlib.util.spec_from_file_location("traffic_analytics_entry", ROOT / "services/traffic-analytics/app.py")
ANALYTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYTICS)


def event(event_type="leader_elected", occurred_at="2026-11-12T10:00:00.000000Z"):
    return {"schema_version": "1.0", "publisher_id": "publisher-a", "session_id": "publisher-0000000001",
            "event_type": event_type, "recovery_id": f"publisher-a/publisher-0000000001/{event_type}/v1",
            "occurred_at": occurred_at, "leader": event_type == "leader_elected"}


class MemoryRecoveryRepository:
    def __init__(self):
        self.items, self.failed = {}, False

    def put(self, value):
        if self.failed:
            raise RuntimeError("storage unavailable")
        value = validate_recovery_event(value)
        key = (value["publisher_id"], value["recovery_id"])
        if key not in self.items:
            self.items[key] = deepcopy(value)
            return "created"
        if self.items[key] != value:
            raise RecoveryConflict("recovery event identity already has different content")
        return "unchanged"

    def get(self, publisher_id, recovery_id):
        if self.failed:
            raise RuntimeError("storage unavailable")
        return self.items.get((publisher_id, recovery_id))

    def query(self, publisher_id, *, from_time=None, to_time=None, limit=50, exclusive_start_key=None):
        if self.failed:
            raise RuntimeError("storage unavailable")
        values = sorted((value for (owner, _), value in self.items.items() if owner == publisher_id),
                        key=lambda value: (value["occurred_at"], value["recovery_id"]))
        values = [value for value in values if (not from_time or value["occurred_at"] >= from_time)
                  and (not to_time or value["occurred_at"] < to_time)]
        start = 0
        if exclusive_start_key:
            marker = exclusive_start_key["recovery_key"]
            start = next(index + 1 for index, value in enumerate(values)
                         if f"{value['occurred_at']}#{value['recovery_id']}" == marker)
        items = values[start:start + limit]
        next_key = None
        if start + limit < len(values):
            last = items[-1]
            next_key = {"publisher_id": publisher_id,
                        "recovery_key": f"{last['occurred_at']}#{last['recovery_id']}"}
        return items, next_key


class RecoveryEventTests(unittest.TestCase):
    def setUp(self):
        self.repository = MemoryRecoveryRepository()
        self.app = ANALYTICS.create_app()
        self.client = self.enterContext(TestClient(self.app))
        self.app.state.recovery_repository = self.repository

    def test_contract_replay_scoped_query_and_storage_failure(self):
        first = event()
        second = event("session_suspended", "2026-11-12T10:01:00.000000Z")
        for expected, value in (("created", first), ("unchanged", first), ("created", second)):
            response = self.client.post("/internal/recovery-events", json=value)
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["status"], expected)
        conflict = {**first, "leader": False}
        self.assertEqual(self.client.post("/internal/recovery-events", json=conflict).status_code, 409)
        self.assertEqual(self.client.post("/internal/recovery-events", json={**first, "recovery_id": "bad"}).status_code, 422)

        page = self.client.get("/traffic/recovery-events", params={"publisher_id": "publisher-a", "limit": 1})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["items"][0]["recovery_id"], first["recovery_id"])
        following = self.client.get("/traffic/recovery-events", params={"publisher_id": "publisher-a", "limit": 1,
                                                                          "cursor": page.json()["next_cursor"]})
        self.assertEqual(following.status_code, 200)
        self.assertEqual(following.json()["items"][0]["recovery_id"], second["recovery_id"])
        detail = self.client.get("/traffic/recovery-events/" + first["recovery_id"],
                                 params={"publisher_id": "publisher-a"})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["event_type"], "leader_elected")
        bounded = self.client.get("/traffic/recovery-events", params={"publisher_id": "publisher-a",
                                                                        "from": first["occurred_at"],
                                                                        "to": second["occurred_at"]})
        self.assertEqual([item["recovery_id"] for item in bounded.json()["items"]], [first["recovery_id"]])
        self.assertEqual(self.client.get("/traffic/recovery-events", params={"publisher_id": "publisher-a",
                                                                                "from": "bad"}).status_code, 422)

        self.repository.failed = True
        self.assertEqual(self.client.get("/traffic/recovery-events", params={"publisher_id": "publisher-a"}).status_code, 503)

