"""Check the six Kubernetes service image build specifications without building images."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    "sensor-registry", "traffic-ingestion", "event-publisher",
    "signal-recommendation", "incident-manager", "traffic-analytics",
)


def main():
    dockerfile = ROOT / "infrastructure" / "container" / "Dockerfile"
    required = ("python:3.14-slim", "requirements-lock.txt", "contracts", "services", "uvicorn app:app")
    source = dockerfile.read_text(encoding="utf-8")
    missing = [item for item in required if item not in source]
    absent = [name for name in SERVICES if not (ROOT / "services" / name / "app.py").is_file()]
    if missing or absent:
        raise SystemExit(f"invalid Phase 8 package specification: missing={missing}, services={absent}")
    for name in SERVICES:
        print(f"docker build -f infrastructure/container/Dockerfile --build-arg SERVICE_DIR=services/{name} -t smarttraffic/{name}:LOCAL .")


if __name__ == "__main__":
    main()
