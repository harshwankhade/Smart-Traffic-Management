"""Local HTTP demo with persistence across actual service-process restarts."""
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from smoke import PROCESS_OPTIONS, ROOT, python_command


class LocalService:
    def __init__(self, name, temporary, environment, port=0):
        self.name, self.temporary, self.environment = name, Path(temporary), environment
        self.port = port
        self.process = None
        self.log = None
        self.base = None

    def start(self):
        self.port_file = self.temporary / f"{self.name}-{uuid4().hex}.json"
        self.log = (self.temporary / f"{self.name}-{uuid4().hex}.log").open("w+", encoding="utf-8")
        self.process = subprocess.Popen(
            python_command(ROOT / "scripts/run_service.py", self.name, "--port", str(self.port),
                           "--port-file", str(self.port_file)),
            cwd=ROOT, env={**os.environ, **self.environment}, stdout=self.log, stderr=self.log,
            **PROCESS_OPTIONS)
        deadline = time.monotonic() + 30
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError(f"{self.name} exited during startup")
                    try:
                        info = json.loads(self.port_file.read_text())
                        if info["pid"] != self.process.pid:
                            raise AssertionError("Server process ownership mismatch")
                        self.base = f"http://127.0.0.1:{info['port']}"
                        if client.get(self.base + "/healthz").status_code == 200:
                            return self
                    except (OSError, ValueError, httpx.HTTPError):
                        time.sleep(0.1)
                raise TimeoutError(f"{self.name} startup timed out")
        except BaseException:
            self.log.flush()
            self.log.seek(0)
            detail = self.log.read()
            self.stop()
            if detail:
                print(detail)
            raise

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None and not self.log.closed:
            self.log.close()


def validate(name, data):
    schema = json.loads((ROOT / "contracts/v1" / f"{name}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


def run(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "SENSOR_REGISTRY_DATABASE_URL": f"sqlite:///{(data_dir / 'registry.db').as_posix()}",
        "INCIDENT_MANAGER_DATABASE_URL": f"sqlite:///{(data_dir / 'incidents.db').as_posix()}",
    }
    with tempfile.TemporaryDirectory(prefix="traffic-phase2-demo-") as temp, httpx.Client(trust_env=False, timeout=5) as http:
        registry = LocalService("sensor-registry", temp, environment)
        incident = LocalService("incident-manager", temp, environment)

        def call(service, method, path, status=200, payload=None, contract=None):
            response = http.request(method, service.base + path, json=payload)
            if response.status_code != status:
                raise AssertionError(f"{method} {path}: expected {status}, got {response.status_code}: {response.text}")
            data = response.json()
            if contract:
                validate(contract, data)
            return data

        try:
            registry.start()
            incident.environment["SENSOR_REGISTRY_URL"] = registry.base
            incident.start()
            suffix = uuid4().hex[:12]
            intersection_id, sensor_id, incident_id = f"int-{suffix}", f"sensor-{suffix}", f"inc-{suffix}"
            call(registry, "POST", "/intersections", 201,
                 {"intersection_id": intersection_id, "name": "Teacher demo", "location": "North"}, "intersection")
            call(registry, "PATCH", f"/intersections/{intersection_id}", payload={"location": "North approach"}, contract="intersection")
            call(registry, "POST", "/sensors", 201,
                 {"sensor_id": sensor_id, "intersection_id": intersection_id, "location": "Lane 1", "status": "active"}, "sensor")
            sensor = call(registry, "PATCH", f"/sensors/{sensor_id}", payload={"status": "inactive"}, contract="sensor")
            original = call(incident, "POST", "/incidents", 201,
                            {"incident_id": incident_id, "intersection_id": intersection_id, "type": "closure", "description": "Simulated closure"}, "incident")
            resolved = call(incident, "PATCH", f"/incidents/{incident_id}", payload={"status": "resolved"}, contract="incident")
            assert resolved["event_id"] != original["event_id"]
            assert call(incident, "PATCH", f"/incidents/{incident_id}", payload={"status": "resolved"}) == resolved
            call(incident, "PATCH", f"/incidents/{incident_id}", 409, {"status": "open"})
            print("PASS real HTTP: intersection/sensor create-update; incident create-resolve; terminal state and retry")

            registry.stop()
            outage_id = f"outage-{suffix}"
            call(incident, "POST", "/incidents", 503,
                 {"incident_id": outage_id, "intersection_id": intersection_id, "type": "closure", "description": "Must not persist"})
            call(incident, "GET", f"/incidents/{outage_id}", 404)
            print("PASS Registry process outage: 503 and no partial incident")
            incident.stop()
            registry.start()
            incident.environment["SENSOR_REGISTRY_URL"] = registry.base
            incident.start()
            assert call(registry, "GET", f"/sensors/{sensor_id}", contract="sensor") == sensor
            assert call(registry, "GET", f"/intersections/{intersection_id}", contract="intersection")["location"] == "North approach"
            assert call(incident, "GET", f"/incidents/{incident_id}", contract="incident") == resolved
            call(incident, "GET", f"/incidents/{outage_id}", 404)
            print("PASS actual process restarts: all records persist; failed incident remains absent")
            print(json.dumps({"intersection_id": intersection_id, "sensor_id": sensor_id,
                              "incident_id": incident_id, "status": "resolved"}, indent=2))
        finally:
            incident.stop()
            registry.stop()
    print(f"PASS demo complete; processes stopped; local records retained in {data_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".data/demo-phase2")
    run(parser.parse_args().data_dir.resolve())
