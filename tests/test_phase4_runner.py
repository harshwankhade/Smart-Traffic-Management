"""Offline checks for the Phase 4 EMR runner's recovery and cleanup boundaries."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from scripts import run_phase4_cloud as runner


class RunnerTests(unittest.TestCase):
    def test_reuse_requires_matching_reviewed_run_and_disabled_guard(self):
        previous = {"project_name": "stp4-expected", "deployment_approved": False}
        reviewed = {"run_name": "stp4-expected", "reviewed_plan": [{"type": "aws_emr_cluster"}]}
        self.assertEqual(runner.choose_run_variables(previous, True, reviewed)["project_name"], "stp4-expected")
        for bad in ({}, {**reviewed, "run_name": "stp4-other"}, {**reviewed, "reviewed_plan": []}):
            with self.assertRaises(RuntimeError):
                runner.choose_run_variables(previous, True, bad)
        with self.assertRaises(RuntimeError):
            runner.choose_run_variables({**previous, "deployment_approved": True}, True, reviewed)

    def test_service_linked_role_baseline_is_recorded_before_apply(self):
        session = Mock()
        iam = session.client.return_value
        iam.get_role.return_value = {"Role": {"Path": "/aws-service-role/kafka.amazonaws.com/"}}
        self.assertEqual(runner.kafka_service_role_before(session), {"present": True})
        iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
        iam.get_role.side_effect = iam.exceptions.NoSuchEntityException()
        self.assertEqual(runner.kafka_service_role_before(session), {"present": False})

    def test_stage_arguments_and_restore_path(self):
        emr = Mock()
        emr.add_job_flow_steps.return_value = {"StepIds": ["s-1"]}
        outputs = {
            "emr_cluster_id": "j-1", "archive_bucket": "test-kafka-bucket",
            "artifact_key": "artifacts/job.jar", "kafka_bootstrap_servers": "private:9098",
        }
        with patch.object(runner, "wait_step"):
            self.assertEqual(runner.submit_job(emr, outputs, "test", 1), "s-1")
            first = emr.add_job_flow_steps.call_args.kwargs["Steps"][0]["HadoopJarStep"]["Args"]
            self.assertEqual(first[first.index("-c") + 1], "com.smarttraffic.FlinkJob")
            self.assertNotIn("-s", first)
            checkpoint = "s3://test-kafka-bucket/checkpoints/test/job/chk-2"
            runner.submit_job(emr, outputs, "test", 2, checkpoint)
            second = emr.add_job_flow_steps.call_args.kwargs["Steps"][0]["HadoopJarStep"]["Args"]
            self.assertEqual(second[second.index("-s") + 1], checkpoint)
        with self.assertRaises(ValueError):
            runner.submit_job(emr, outputs, "test", 2)

    def test_checkpoint_uses_receipted_id_not_latest_object(self):
        s3 = Mock()
        s3.get_object.return_value = {"Body": io.BytesIO(b'{"run":"test","checkpoint_id":2}')}
        s3.get_paginator.return_value.paginate.return_value = [{"Contents": [
            {"Key": "checkpoints/test/job/chk-3/_metadata"},
            {"Key": "checkpoints/test/job/chk-2/_metadata"},
        ]}]
        uri, receipt = runner.wait_checkpoint(s3, "bucket", "test", seconds=1)
        self.assertEqual(uri, "s3://bucket/checkpoints/test/job/chk-2")
        self.assertEqual(receipt["checkpoint_id"], 2)

    def test_marker_result_is_checked_independently(self):
        start = "2026-11-10T10:00:00Z"
        end = "2026-11-10T10:01:00Z"
        result = {
            "schema_version": "1.0", "intersection_id": "test-main", "window_start": start,
            "window_end": end, "window_id": f"test-main/{start}/{end}/v1", "reading_count": 2,
            "vehicle_count_sum": 5, "average_speed": 20, "average_occupancy": 0.6,
            "congestion": "medium",
        }
        runner.validate_result(result, "test", 1)
        with self.assertRaises(AssertionError):
            runner.validate_result({**result, "reading_count": 3}, "test", 1)

    def test_partial_state_recovers_only_exact_run_ids(self):
        document = {"values": {"root_module": {"child_modules": [
            {"resources": [
                {"address": "module.processing.aws_emr_cluster.congestion", "type": "aws_emr_cluster", "values": {"id": "j-run"}},
                {"address": "module.kafka.aws_s3_bucket.archive", "type": "aws_s3_bucket", "values": {"id": "run-kafka-bucket"}},
                {"address": "module.unrelated.aws_s3_bucket.archive", "type": "aws_s3_bucket", "values": {"id": "unrelated"}},
            ]}
        ]}}}
        with patch.object(runner, "tf", return_value=json.dumps(document)):
            self.assertEqual(runner.state_run_resources(), {
                "module.processing.aws_emr_cluster.congestion": "j-run",
                "module.kafka.aws_s3_bucket.archive": "run-kafka-bucket",
            })

    def test_cleanup_attempts_destroy_after_bucket_failure(self):
        session = Mock()
        emr = session.client.return_value
        emr.describe_cluster.return_value = {"Cluster": {"Status": {"State": "TERMINATED"}}}
        emr.get_paginator.return_value.paginate.return_value = [{"Clusters": []}]
        session.client.return_value.list_buckets.return_value = {"Buckets": []}
        session.client.return_value.get_caller_identity.return_value = {"Account": "123456789012"}
        evidence = {}
        owned = {"module.processing.aws_emr_cluster.congestion": "j-run",
                 "module.kafka.aws_s3_bucket.archive": "run-kafka-bucket"}
        with patch.object(runner, "state_emr_security_groups", return_value={}), \
             patch.object(runner, "state_run_resources", return_value=owned), \
             patch.object(runner, "wait_cluster"), \
             patch.object(runner, "empty_versioned_bucket", side_effect=RuntimeError("storage unavailable")), \
             patch.object(runner, "tf", return_value="") as terraform:
            with self.assertRaisesRegex(RuntimeError, "S3 emptying"):
                runner.cleanup(session, "run", evidence)
        self.assertTrue(any(call.args[0] == "destroy" for call in terraform.call_args_list))
        self.assertEqual(evidence["cleanup_run_resources_from_state"], owned)


if __name__ == "__main__":
    unittest.main()
