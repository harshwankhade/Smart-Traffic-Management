"""Offline regression checks for reusable builds and private Kafka clients."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "contracts/python"))
from traffic_contracts.kafka_tls import tls_config
from traffic_contracts.result_consumer import kafka_config
from scripts import prepare_demo_artifacts as builds
from scripts.phase8_start_processor import step


class DemoRuntimeTests(unittest.TestCase):
    def test_tls_fails_closed_and_verifies_hostnames(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                tls_config()
        ca = "-----BEGIN CERTIFICATE-----\nexample\n-----END CERTIFICATE-----"
        with patch.dict(os.environ, {"KAFKA_AUTH_MODE": "tls", "KAFKA_SSL_CA_PEM": ca}):
            config = kafka_config("test")
            self.assertEqual(config["security.protocol"], "SSL")
            self.assertEqual(config["ssl.ca.pem"], ca)
            self.assertTrue(config["enable.ssl.certificate.verification"])
            self.assertEqual(config["ssl.endpoint.identification.algorithm"], "https")
            path = ROOT / "services/event-publisher/publisher/adapters.py"
            spec = importlib.util.spec_from_file_location("demo_publisher_adapters", path)
            adapters = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapters)
            self.assertEqual(adapters.kafka_config()["ssl.ca.pem"], ca)

    def test_source_cache_invalidates_on_changes_and_ignores_build_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".data") as directory:
            root = Path(directory)
            (root / "source").mkdir()
            source = root / "source/app.py"
            source.write_text("first")
            with patch.object(builds, "ROOT", root):
                first = builds.fingerprint(["source"])
                (root / "source/target").mkdir()
                (root / "source/target/binary.jar").write_text("build output")
                self.assertEqual(first, builds.fingerprint(["source"]))
                source.write_text("changed")
                self.assertNotEqual(first, builds.fingerprint(["source"]))
                manifest = {"revision": "r", "sha256": {"artifact": builds.binary_hash(source)}}
                self.assertTrue(builds.cached(manifest, "r", {"artifact": source}))
                source.write_text("corrupted")
                self.assertFalse(builds.cached(manifest, "r", {"artifact": source}))

    def test_checkpoint_guard_ignores_directory_markers_but_keeps_real_state(self):
        import jmespath
        from scripts.phase8_start_processor import CHECKPOINT_FILES_QUERY
        for data, expected in [({}, []),
                ({'Contents': [{'Key': 'checkpoints/demo/job/shared/', 'Size': 0}]}, []),
                ({'Contents': [{'Key': 'checkpoints/demo/job/shared/', 'Size': 0},
                               {'Key': 'checkpoints/demo/job/chk-1/_metadata', 'Size': 100}]},
                 ['checkpoints/demo/job/chk-1/_metadata'])]:
            self.assertEqual(jmespath.search(CHECKPOINT_FILES_QUERY, data), expected)

    def test_step_uses_tls_and_refuses_implicit_rebuild_or_foreign_checkpoint(self):
        outputs = {"flink_artifact_uri": "s3://demo/artifacts/processor.jar",
                   "kafka_ca_uri": "s3://demo/artifacts/kafka-ca.pem",
                   "kafka_bootstrap_servers": "kafka.smarttraffic.internal:9093",
                   "archive_bucket": "demo"}
        script = step(outputs)["HadoopJarStep"]["Args"][-1]
        self.assertIn("--KAFKA_AUTH_MODE tls", script)
        self.assertIn("--KAFKA_SSL_CA_LOCATION", script)
        self.assertIn("Existing checkpoints require", script)
        self.assertIn("RUNNING,ACCEPTED", script)
        checkpoint = "s3://demo/checkpoints/demo/job/chk-1"
        self.assertIn("-s " + checkpoint, step(outputs, checkpoint)["HadoopJarStep"]["Args"][-1])
        with self.assertRaises(ValueError):
            step(outputs, "s3://other/checkpoints/chk-1")


if __name__ == "__main__":
    unittest.main()
