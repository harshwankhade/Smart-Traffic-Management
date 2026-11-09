"""Check the prescribed boundaries without claiming application behavior."""

import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.TestCase):
    def test_exact_prescribed_service_set_and_placement(self):
        catalog = json.loads((ROOT / "services/catalog.json").read_text())
        expected = {
            "sensor-registry", "traffic-ingestion", "event-publisher",
            "congestion-processor", "signal-recommendation", "incident-manager",
            "alert-service", "traffic-analytics",
        }
        self.assertEqual(len(catalog), 8)
        self.assertEqual({entry["name"] for entry in catalog}, expected)
        self.assertEqual(Counter(entry["placement"] for entry in catalog),
                         {"kubernetes": 6, "managed-flink": 1, "serverless": 1})
        for name in expected:
            self.assertTrue((ROOT / "services" / name / "README.md").is_file(), name)


if __name__ == "__main__":
    unittest.main()
