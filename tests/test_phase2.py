"""Phase 2 API, ownership, persistence and failure behavior."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts" / "python"))
for name in ("sensor-registry", "incident-manager"):
    sys.path.insert(0, str(ROOT / "services" / name))


def module(service):
    spec = importlib.util.spec_from_file_location(service.replace("-", "_"), ROOT / "services" / service / "app.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


REGISTRY = module("sensor-registry")
INCIDENTS = module("incident-manager")


def validates(name, record):
    schema = json.loads((ROOT / "contracts/v1" / f"{name}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="traffic-phase2-test-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.registry_url = f"sqlite:///{(base / 'registry.db').as_posix()}"
        self.incident_url = f"sqlite:///{(base / 'incidents.db').as_posix()}"
        self.registry_app = REGISTRY.create_app(self.registry_url)
        self.registry = self.enterContext(TestClient(self.registry_app))
        self.calls = []
        self.registry_mode = "normal"

        def transport(request):
            self.calls.append(request)
            if self.registry_mode == "timeout":
                raise httpx.ReadTimeout("simulated", request=request)
            if self.registry_mode == "failure":
                return httpx.Response(500)
            if self.registry_mode == "malformed":
                return httpx.Response(200, json={"wrong": "response"})
            response = self.registry.get(request.url.path)
            return httpx.Response(response.status_code, json=response.json())

        self.incident_app = INCIDENTS.create_app(self.incident_url, registry_transport=httpx.MockTransport(transport))
        self.incidents = self.enterContext(TestClient(self.incident_app))
        self.intersection = {"intersection_id": "int-01", "name": "Demo", "location": "North"}
        self.sensor = {"sensor_id": "sensor-01", "intersection_id": "int-01", "location": "Approach", "status": "active"}
        self.incident = {"incident_id": "inc-01", "intersection_id": "int-01", "type": "closure", "description": "Demo closure"}

    def seed(self):
        self.assertEqual(self.registry.post("/intersections", json=self.intersection).status_code, 201)

    def create_incident(self):
        self.seed()
        response = self.incidents.post("/incidents", json=self.incident)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_registry_crud_and_response_contracts(self):
        self.seed()
        response = self.registry.patch("/intersections/int-01", json={"name": "Updated", "location": "South"})
        self.assertEqual(response.status_code, 200)
        validates("intersection", response.json())
        self.assertEqual(self.registry.get("/intersections/int-01").json()["location"], "South")
        response = self.registry.post("/sensors", json=self.sensor)
        self.assertEqual(response.status_code, 201)
        validates("sensor", response.json())
        response = self.registry.patch("/sensors/sensor-01", json={"status": "inactive", "location": "East"})
        self.assertEqual(response.status_code, 200)
        validates("sensor", response.json())
        self.assertEqual(self.registry.get("/sensors/sensor-01").json()["status"], "inactive")

    def test_duplicates_and_unknown_records(self):
        self.seed()
        self.assertEqual(self.registry.post("/intersections", json=self.intersection).status_code, 409)
        self.assertEqual(self.registry.post("/sensors", json=self.sensor).status_code, 201)
        self.assertEqual(self.registry.post("/sensors", json=self.sensor).status_code, 409)
        for path in ("/sensors/missing", "/intersections/missing"):
            self.assertEqual(self.registry.get(path).status_code, 404)
            self.assertEqual(self.registry.patch(path, json={"location": "New"}).status_code, 404)
        self.assertEqual(self.incidents.get("/incidents/missing").status_code, 404)
        self.assertEqual(self.incidents.patch("/incidents/missing", json={"status": "resolved"}).status_code, 404)

    def test_unknown_references_do_not_persist(self):
        self.assertEqual(self.registry.post("/sensors", json=self.sensor).status_code, 422)
        self.assertEqual(self.registry.get("/sensors/sensor-01").status_code, 404)
        self.assertEqual(self.incidents.post("/incidents", json=self.incident).status_code, 422)
        self.assertEqual(self.incidents.get("/incidents/inc-01").status_code, 404)

    def test_incident_metadata_transitions_and_noops(self):
        original = self.create_incident()
        validates("incident", original)
        self.assertEqual(original["status"], "open")
        self.assertEqual(original["reported_at"], original["updated_at"])
        self.assertEqual(self.incidents.patch("/incidents/inc-01", json={"status": "open"}).json(), original)
        changed = self.incidents.patch("/incidents/inc-01", json={"description": "Updated closure"}).json()
        self.assertNotEqual(changed["event_id"], original["event_id"])
        self.assertEqual(changed["reported_at"], original["reported_at"])
        self.assertGreaterEqual(changed["updated_at"], original["updated_at"])
        resolved = self.incidents.patch("/incidents/inc-01", json={"status": "resolved"}).json()
        validates("incident", resolved)
        self.assertNotEqual(changed["event_id"], resolved["event_id"])
        self.assertEqual(self.incidents.patch("/incidents/inc-01", json={"status": "resolved"}).json(), resolved)
        self.assertEqual(self.incidents.patch("/incidents/inc-01", json={"status": "open", "description": "Must not persist"}).status_code, 409)
        self.assertEqual(self.incidents.get("/incidents/inc-01").json(), resolved)
        calls_before = len(self.calls)
        self.assertEqual(self.incidents.post("/incidents", json=self.incident).status_code, 409)
        self.assertEqual(len(self.calls), calls_before)

    def test_dependency_errors_have_no_partial_incident_or_retry(self):
        self.seed()
        for mode in ("timeout", "failure", "malformed"):
            with self.subTest(mode=mode):
                self.registry_mode = mode
                before = len(self.calls)
                response = self.incidents.post("/incidents", json=self.incident)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(self.calls[-1].extensions["timeout"]["read"], 2.0)
                self.assertEqual(self.incidents.get("/incidents/inc-01").status_code, 404)
        self.registry_mode = "normal"
        self.assertEqual(self.incidents.post("/incidents", json=self.incident).status_code, 201)

    def test_rejects_invalid_input_immutable_fields_and_empty_patches(self):
        self.create_incident()
        self.assertEqual(self.registry.post("/sensors", json=self.sensor).status_code, 201)
        cases = [
            (self.registry, "post", "/intersections", {**self.intersection, "extra": 1}),
            (self.registry, "post", "/intersections", {**self.intersection, "intersection_id": ""}),
            (self.registry, "post", "/sensors", {**self.sensor, "status": "deleted"}),
            (self.registry, "patch", "/sensors/sensor-01", {"intersection_id": "other"}),
            (self.registry, "patch", "/intersections/int-01", {"intersection_id": "other"}),
            (self.incidents, "post", "/incidents", {**self.incident, "event_id": "client"}),
            (self.incidents, "post", "/incidents", {**self.incident, "status": "resolved"}),
            (self.incidents, "post", "/incidents", {**self.incident, "reported_at": "2020-01-01T00:00:00Z"}),
            (self.incidents, "post", "/incidents", {**self.incident, "type": "invalid"}),
            (self.incidents, "post", "/incidents", {**self.incident, "description": " "}),
            (self.incidents, "patch", "/incidents/inc-01", {"type": "collision"}),
        ]
        for client, method, path, payload in cases:
            with self.subTest(path=path, payload=payload):
                self.assertEqual(getattr(client, method)(path, json=payload).status_code, 422)
        for client, path in ((self.registry, "/sensors/sensor-01"), (self.registry, "/intersections/int-01"),
                             (self.incidents, "/incidents/inc-01")):
            for payload in ({}, {"status": None} if "intersections" not in path else {"name": None}):
                self.assertEqual(client.patch(path, json=payload).status_code, 422)

    def test_owned_tables_fk_and_persistence_across_new_apps(self):
        self.create_incident()
        self.registry.post("/sensors", json=self.sensor)
        reg_db = self.registry_app.state.database
        inc_db = self.incident_app.state.database
        self.assertEqual(set(inspect(reg_db.engine).get_table_names()), {"sensors", "intersections"})
        self.assertEqual(set(inspect(inc_db.engine).get_table_names()), {"incidents", "alert_outbox"})
        with reg_db.engine.connect() as connection:
            self.assertEqual(connection.execute(text("PRAGMA foreign_keys")).scalar(), 1)
        from registry.models import SensorRow
        with reg_db.sessions() as session:
            session.add(SensorRow(sensor_id="bad", intersection_id="absent", location="x", status="active"))
            with self.assertRaises(IntegrityError):
                session.commit()
        with TestClient(REGISTRY.create_app(self.registry_url)) as restarted:
            self.assertEqual(restarted.get("/sensors/sensor-01").status_code, 200)
        with TestClient(INCIDENTS.create_app(self.incident_url)) as restarted:
            self.assertEqual(restarted.get("/incidents/inc-01").status_code, 200)

    def test_stale_incident_update_cannot_overwrite_resolution(self):
        self.create_incident()
        from incidents.models import IncidentRow
        with self.incident_app.state.database.sessions() as first, self.incident_app.state.database.sessions() as second:
            a = first.get(IncidentRow, "inc-01")
            b = second.get(IncidentRow, "inc-01")
            a.status = "resolved"
            first.commit()
            b.description = "stale write"
            with self.assertRaises(StaleDataError):
                second.commit()

    def test_database_failure_returns_503_without_details(self):
        with self.incident_app.state.database.engine.begin() as connection:
            connection.execute(text("DROP TABLE incidents"))
        response = self.incidents.get("/incidents/missing")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Incident database unavailable"})

    def test_explicit_initialization_tools_keep_tables_separate(self):
        for service, variable, filename, tables in (
            ("sensor-registry", "SENSOR_REGISTRY_DATABASE_URL", "init-registry.db", {"intersections", "sensors"}),
            ("incident-manager", "INCIDENT_MANAGER_DATABASE_URL", "init-incidents.db", {"incidents", "alert_outbox"}),
        ):
            with self.subTest(service=service):
                database_file = Path(self.temp.name) / filename
                subprocess.run([sys.executable, str(ROOT / "scripts/init_database.py"), service],
                               cwd=ROOT, env={**os.environ, variable: f"sqlite:///{database_file.as_posix()}"},
                               capture_output=True, text=True, timeout=15, check=True,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                from sqlalchemy import create_engine
                engine = create_engine(f"sqlite:///{database_file.as_posix()}")
                try:
                    self.assertEqual(set(inspect(engine).get_table_names()), tables)
                finally:
                    engine.dispose()

    def test_openapi_and_existing_health(self):
        for client, service in ((self.registry, "sensor-registry"), (self.incidents, "incident-manager")):
            self.assertEqual(client.get("/healthz").json(), {"service": service, "status": "ok", "scope": "scaffold"})
            self.assertEqual(client.get("/docs").status_code, 200)
            self.assertEqual(client.get("/openapi.json").status_code, 200)


if __name__ == "__main__":
    unittest.main()
