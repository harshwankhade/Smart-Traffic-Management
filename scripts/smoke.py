"""Check six real HTTP processes and both non-HTTP scaffold entry points."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))
PROCESS_OPTIONS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def python_command(script, *arguments):
    # On Windows the venv executable can be a redirector. Launch the actual
    # interpreter so terminate()/wait() own the server, not only its launcher.
    executable = getattr(sys, "_base_executable", None) or sys.executable
    bootstrap = (
        "import runpy,sys; "
        f"sys.path[:] = {sys.path!r}; "
        f"sys.argv = {[str(script), *arguments]!r}; "
        f"runpy.run_path({str(script)!r}, run_name='__main__')"
    )
    return [executable, "-c", bootstrap]


def expected(service):
    return {"service": service, "status": "ok", "scope": "scaffold"}


def request(url, method="GET"):
    with HTTP.open(Request(url, method=method), timeout=1) as response:
        return json.load(response)


def verify_absent(url, code, method="GET"):
    try:
        request(url, method)
    except HTTPError as error:
        if error.code == code:
            return
        raise AssertionError(f"{method} {url}: expected {code}, got {error.code}") from error
    raise AssertionError(f"{method} {url}: unexpectedly accepted")


def check_entrypoint(command, service):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            timeout=30, check=True, **PROCESS_OPTIONS)
    if json.loads(result.stdout) != expected(service):
        raise AssertionError(f"Incorrect smoke response from {service}")
    print(f"PASS {service}: local entry point (no cloud runtime)")


def main():
    for tool in ("javac", "java"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} is required; install JDK 17+ and retry")
    catalog = json.loads((ROOT / "services/catalog.json").read_text())
    processes = []
    logs = []
    try:
        with tempfile.TemporaryDirectory(prefix="smart-traffic-smoke-") as temporary:
            temp = Path(temporary)
            try:
                for entry in catalog:
                    if entry["placement"] != "kubernetes":
                        continue
                    name = entry["name"]
                    port_file = temp / f"{name}.json"
                    log = (temp / f"{name}.log").open("w+", encoding="utf-8")
                    logs.append((name, log))
                    process = subprocess.Popen(
                        python_command(ROOT / "scripts/run_service.py", name,
                                       "--port", "0", "--port-file", str(port_file)),
                        cwd=ROOT, stdout=log, stderr=log,
                        env={**os.environ,
                             "SENSOR_REGISTRY_DATABASE_URL": f"sqlite:///{(temp / 'registry.db').as_posix()}",
                             "INCIDENT_MANAGER_DATABASE_URL": f"sqlite:///{(temp / 'incidents.db').as_posix()}"},
                        **PROCESS_OPTIONS)
                    processes.append((name, process, port_file))

                for name, process, port_file in processes:
                    deadline = time.monotonic() + 30
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"{name} exited with {process.returncode}")
                        try:
                            server_info = json.loads(port_file.read_text())
                            if server_info["pid"] != process.pid:
                                raise AssertionError(f"{name}: server escaped child-process ownership")
                            port = server_info["port"]
                            base = f"http://127.0.0.1:{port}"
                            data = request(base + "/healthz")
                            break
                        except (OSError, URLError, json.JSONDecodeError):
                            if time.monotonic() >= deadline:
                                raise TimeoutError(f"{name} failed to start within 30 seconds")
                            time.sleep(0.1)
                    if data != expected(name):
                        raise AssertionError(f"Incorrect health response for {name}: {data}")
                    implemented = name in ("sensor-registry", "incident-manager")
                    if implemented:
                        document = request(base + "/openapi.json")
                        own = "/sensors" if name == "sensor-registry" else "/incidents"
                        if own not in document["paths"]:
                            raise AssertionError(f"{name}: implemented routes missing from OpenAPI")
                        verify_absent(base + own, 405)
                        verify_absent(base + ("/incidents" if name == "sensor-registry" else "/sensors"), 404)
                    else:
                        for path in ("/docs", "/openapi.json", "/sensors", "/incidents"):
                            verify_absent(base + path, 404)
                    verify_absent(base + "/readings", 404)
                    verify_absent(base + "/healthz", 405, "POST")
                    print(f"PASS {name}: HTTP health; " + ("Phase 2 routes documented" if implemented else "business/docs routes absent"))

                check_entrypoint(python_command(ROOT / "services/alert-service/handler.py",
                                               "--smoke"), "alert-service")
                source = ROOT / "services/congestion-processor/src/main/java/com/smarttraffic/CongestionProcessor.java"
                subprocess.run(["javac", "--release", "17", "-d", str(temp), str(source)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30,
                               check=True, **PROCESS_OPTIONS)
                classfile = temp / "com/smarttraffic/CongestionProcessor.class"
                if int.from_bytes(classfile.read_bytes()[6:8], "big") != 61:
                    raise AssertionError("Java scaffold did not compile to Java 17 bytecode")
                check_entrypoint(["java", "-cp", str(temp), "com.smarttraffic.CongestionProcessor",
                                  "--smoke"], "congestion-processor")
                print("PASS Java 17 bytecode target; no Flink dependencies loaded")
            except BaseException:
                for name, log in logs:
                    log.flush()
                    log.seek(0)
                    detail = log.read()
                    if detail:
                        print(f"{name} log:\n{detail}", file=sys.stderr)
                raise
            finally:
                for _, process, _ in processes:
                    if process.poll() is None:
                        process.terminate()
                for _, process, _ in processes:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                for _, log in logs:
                    log.close()
        print("PASS all 8 scaffold entry points; child processes stopped")
    except subprocess.CalledProcessError as error:
        print(error.stderr or str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
