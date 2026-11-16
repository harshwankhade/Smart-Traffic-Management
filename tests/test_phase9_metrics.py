"""Focused checks for bounded Prometheus HTTP metrics."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "contracts" / "python")]
from traffic_contracts.metrics import install_http_metrics  # noqa: E402


class HttpMetricsTests(unittest.TestCase):
    def test_records_a_template_route_and_excludes_scrapes(self):
        app = FastAPI()
        install_http_metrics(app, "test-service")

        @app.get("/items/{identifier}")
        def item(identifier):
            return {"identifier": identifier}

        with TestClient(app) as client:
            self.assertEqual(client.get("/items/private-event-id").status_code, 200)
            body = client.get("/metrics").text

        self.assertIn('smarttraffic_http_requests_total{service="test-service",method="GET",route="/items/{identifier}",status="200"} 1', body)
        self.assertNotIn("private-event-id", body)
        self.assertNotIn('route="/metrics"', body)
        self.assertIn("smarttraffic_http_request_duration_seconds_bucket", body)


if __name__ == "__main__":
    unittest.main()
