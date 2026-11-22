"""Account switches must fail closed and never reuse another account's state."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch, call

from scripts import project_aws as account
from scripts import phase8_publish_images as publisher

CONFIG = {"profile": "new-sdk", "account_id": "123456789012", "region": "ap-south-1"}


class ProjectAccountTests(unittest.TestCase):
    def test_returning_account_uses_preserved_state_and_blocks_unreviewed_plan(self):
        config = {**CONFIG, "state_layout": "existing"}
        original = account.ROOT / "infrastructure/terraform/phase8"
        self.assertEqual(account.state_directory(config, "phase8"), original)
        self.assertEqual(account.working_directory(config, "phase8"), original)
        self.assertEqual(account.environment(config, "phase8")["TF_DATA_DIR"], str(original / ".terraform"))
        self.assertIn(f"-chdir={original}", account.terraform_command(config, "phase8", "state-list"))
        with self.assertRaises(RuntimeError):
            account.terraform_command(config, "phase8-dns", "plan")

    def test_original_state_ownership_mismatch_preserves_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "infrastructure/terraform/phase8"
            source.mkdir(parents=True)
            (source / "terraform.tfstate").write_text(json.dumps({"arn": "arn:aws:eks:ap-south-1:999999999999:cluster/old"}))
            selection = root / "selection.json"
            selection.write_text("previous selection")
            with patch.object(account, "ROOT", root), patch.object(account, "SELECTION", selection), patch.object(account, "verify_identity"):
                with self.assertRaises(RuntimeError):
                    account.configure({**CONFIG, "state_layout": "existing"})
            self.assertEqual(selection.read_text(), "previous selection")

    def test_identity_mismatch_does_not_write_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(account, "ROOT", Path(directory)), patch.object(account, "SELECTION", Path(directory) / "selection.json"), patch.object(account.subprocess, "run", return_value=Mock(stdout=json.dumps({"Account": "999999999999"}))):
                with self.assertRaises(RuntimeError):
                    account.configure(CONFIG)
                self.assertFalse(account.SELECTION.exists())

    def test_initialization_uses_separate_state_without_migration(self):
        command = account.terraform_command(CONFIG, "phase8", "init")
        self.assertIn("-reconfigure", command)
        self.assertNotIn("-migrate-state", command)
        state_argument = next(arg for arg in command if arg.startswith("-backend-config=path="))
        self.assertIn("123456789012", state_argument)
        self.assertIn("aws-accounts", state_argument)
        self.assertNotEqual(account.account_directory(CONFIG), account.account_directory({**CONFIG, "account_id": "999999999999"}))

    def test_environment_removes_old_credential_and_workspace_overrides(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "old", "AWS_SECRET_ACCESS_KEY": "old",
                                     "TF_WORKSPACE": "old", "TF_CLI_ARGS_plan": "-state=old"}):
            env = account.environment(CONFIG, "phase8")
        self.assertEqual(env["AWS_PROFILE"], "new-sdk")
        self.assertIn("123456789012", env["TF_DATA_DIR"])
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "TF_WORKSPACE", "TF_CLI_ARGS_plan"):
            self.assertNotIn(key, env)

    def test_pending_runtime_inputs_cannot_trigger_plan(self):
        with self.assertRaises(RuntimeError):
            account.terraform_command(CONFIG, "phase8", "plan")
        variables = account.variables(CONFIG, "phase8")
        self.assertFalse(variables["deployment_approved"])
        self.assertEqual(variables["expected_account_id"], CONFIG["account_id"])
        self.assertEqual(variables["admin_cidrs"], [])
        with self.assertRaises(ValueError):
            account.terraform_command(CONFIG, "phase8", "apply")

    def test_working_copy_never_copies_old_state_or_account_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "infrastructure/terraform/phase8"
            source.mkdir(parents=True)
            for name in ("main.tf", "terraform.tfstate", "terraform.tfvars", "secrets.auto.tfvars.json", "old-plan.txt"):
                (source / name).write_text("test")
            with patch.object(account, "ROOT", root):
                account.sync_configuration(CONFIG)
                working = account.account_directory(CONFIG) / "configuration/infrastructure/terraform/phase8"
                self.assertEqual([p.name for p in working.iterdir()], ["main.tf"])
                self.assertTrue((source / "terraform.tfstate").exists())

    def test_cross_account_repository_output_is_rejected_before_ecr_access(self):
        with tempfile.TemporaryDirectory() as directory:
            repositories = Path(directory) / "repositories.json"
            repositories.write_text(json.dumps({service: f"999999999999.dkr.ecr.ap-south-1.amazonaws.com/demo/{service}"
                                                for service in publisher.SERVICES}))
            session = Mock()
            session.client.return_value.get_caller_identity.return_value = {"Account": CONFIG["account_id"]}
            with patch("sys.argv", ["publisher", "--repositories-json", str(repositories), "--tag", "test"]), patch.object(publisher.boto3, "Session", return_value=session):
                with self.assertRaisesRegex(RuntimeError, "another account"):
                    publisher.main()
            self.assertEqual(session.client.call_args_list, [call("sts")])


if __name__ == "__main__":
    unittest.main()
