"""Run one local service on loopback."""

import argparse
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
PORTS = {
    "sensor-registry": 8001, "traffic-ingestion": 8002,
    "event-publisher": 8003, "signal-recommendation": 8005,
    "incident-manager": 8006, "traffic-analytics": 8008,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=PORTS)
    parser.add_argument("--port", type=int, help="0 selects an available port")
    parser.add_argument("--port-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    port = PORTS[args.service] if args.port is None else args.port
    if not 0 <= port <= 65535:
        parser.error("port must be between 0 and 65535")
    sys.path.insert(0, str(ROOT / "services" / args.service))
    spec = importlib.util.spec_from_file_location(
        "health_service", ROOT / "services" / args.service / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Bind before advertising the port; keep ownership through server startup.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
        if args.port_file:
            args.port_file.write_text(json.dumps({"port": listener.getsockname()[1],
                                                  "pid": os.getpid()}),
                                      encoding="utf-8")
        server = uvicorn.Server(uvicorn.Config(module.app, host="127.0.0.1",
                                               log_level="warning", access_log=False))
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
