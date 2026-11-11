"""Local Phase 6 producer -> queue -> Alert Service demo; no AWS calls."""

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for path in ("contracts/python", "services/incident-manager", "services/signal-recommendation",
             "services/alert-service"):
    sys.path.insert(0, str(ROOT / path))

from alerts import AlertRepository  # noqa: E402
from incidents.database import Database  # noqa: E402
from incidents.outbox import deliver_one  # noqa: E402
from incidents.repository import create  # noqa: E402
from traffic_contracts.alerts import InMemoryAlertSender  # noqa: E402


class MemoryTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item, ConditionExpression):
        if ConditionExpression != "attribute_not_exists(alert_id)":
            raise AssertionError("conditional write required")
        if Item["alert_id"] in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException",
                                          "Message": "exists"}}, "PutItem")
        self.items[Item["alert_id"]] = dict(Item)

    def get_item(self, *, Key, ConsistentRead):
        if not ConsistentRead:
            raise AssertionError("consistent read required")
        return {"Item": self.items[Key["alert_id"]]} if Key["alert_id"] in self.items else {}


class MemoryResource:
    def __init__(self):
        self.table = MemoryTable()

    def Table(self, _):
        return self.table


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*, dynamodb_local=False):
    signal = load("services/signal-recommendation/app.py", "phase6_demo_signal")
    alert_handler = load("services/alert-service/handler.py", "phase6_demo_handler")
    sender = InMemoryAlertSender()
    if dynamodb_local:
        import boto3
        resource = boto3.resource("dynamodb", endpoint_url="http://127.0.0.1:8000",
                                  region_name="ap-south-1", aws_access_key_id="local",
                                  aws_secret_access_key="local")
        repository = AlertRepository(resource=resource)
        repository.table.meta.client.describe_table(TableName=repository.table.name)
    else:
        repository = AlertRepository(resource=MemoryResource())

    class RecommendationStore:
        store = object()

        def __init__(self):
            self.records = {}

        def put(self, item):
            key = item["recommendation_id"]
            if key in self.records and self.records[key] != item:
                raise ValueError("changed recommendation")
            outcome = "unchanged" if key in self.records else "created"
            self.records[key] = item
            return outcome

    class CapturedWorker:
        def __init__(self, _group, _store, persist):
            self.persist = persist

        def start(self):
            pass

        def stop(self):
            pass

    run_id = uuid.uuid4().hex[:12]
    intersection = "p6-demo-" + run_id
    start = "2026-11-11T10:00:00Z"
    end = "2026-11-11T10:01:00Z"
    result = {"schema_version": "1.0", "window_id": f"{intersection}/{start}/{end}/v1",
              "intersection_id": intersection, "window_start": start, "window_end": end,
              "reading_count": 1, "vehicle_count_sum": 5, "average_speed": 10,
              "average_occupancy": 0.9, "congestion": "high"}
    owned = RecommendationStore()
    with patch.dict(os.environ, {"PHASE5_CONSUMER_ENABLED": "1"}), patch.object(signal, "ResultConsumer", CapturedWorker):
        app = signal.create_app(repository=owned, alert_sender=sender)
        with TestClient(app):
            app.state.worker.persist(result)
            app.state.worker.persist(result)  # Same Kafka result delivered again.
    assert len(owned.records) == 1

    with tempfile.TemporaryDirectory(prefix="phase6-alert-demo-") as directory:
        database = Database("sqlite:///" + (Path(directory) / "incidents.db").as_posix())
        database.initialize()
        try:
            with database.sessions() as session:
                create(session, {"incident_id": "inc-" + run_id, "intersection_id": intersection,
                                 "type": "closure", "description": "simulated closure"})
            assert deliver_one(database, sender)
            assert not deliver_one(database, sender)
        finally:
            database.engine.dispose()

    batch = {"Records": [{"messageId": str(index), "eventSource": "aws:sqs", "body": body}
                         for index, body in enumerate(sender.messages, 1)]}
    first = alert_handler.process_batch(batch, repository)
    second = alert_handler.process_batch(batch, repository)
    assert first == second == {"batchItemFailures": []}
    ids = {json.loads(body)["alert_id"] for body in sender.messages}
    assert len(ids) == 2
    assert all(repository.get(identifier)["outcome"] == "recorded" for identifier in ids)
    print(json.dumps({"mode": "dynamodb-local" if dynamodb_local else "memory-store",
                      "queue_messages": len(sender.messages), "logical_alerts": len(ids),
                      "replay_failures": len(second["batchItemFailures"]), "passed": True}))
    if dynamodb_local:
        for identifier in ids:
            repository.table.delete_item(Key={"alert_id": identifier})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamodb-local", action="store_true")
    run(dynamodb_local=parser.parse_args().dynamodb_local)
