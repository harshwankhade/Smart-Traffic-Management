"""Select a verified AWS account and isolate Terraform preparation from old state.

Configure writes ignored local metadata only. Supported Terraform operations are
init, validate, plan, output and state list. Apply/destroy and DNS changes remain
separate tasks; no state is copied or migrated by this helper.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / ".data/aws-account.json"
ROOTS = ("phase8", "phase8-artifacts", "phase8-dns")


def environment(config, root=None):
    env = dict(os.environ)
    for key in list(env):
        if key in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                   "AWS_SECURITY_TOKEN", "AWS_DEFAULT_PROFILE", "TF_WORKSPACE"} or key.startswith("TF_CLI_ARGS"):
            env.pop(key)
    env.update(AWS_PROFILE=config["profile"], AWS_REGION=config["region"],
               AWS_DEFAULT_REGION=config["region"], TF_VAR_expected_account_id=config["account_id"])
    if root:
        env["TF_DATA_DIR"] = str(working_directory(config, root) / ".terraform" if config.get("state_layout") == "existing" else account_directory(config) / root / "terraform-data")
    return env


def account_directory(config):
    account = config["account_id"]
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("Account ID must have exactly 12 digits")
    return ROOT / ".data/aws-accounts" / account


def working_directory(config, root):
    if config.get("state_layout") == "existing":
        return ROOT / "infrastructure/terraform" / root
    return account_directory(config) / "configuration/infrastructure/terraform" / root


def state_directory(config, root):
    return working_directory(config, root) if config.get("state_layout") == "existing" else account_directory(config) / root


def sync_configuration(config):
    """Copy source only, never old state, variables, plans, logs or credentials.

    A new TF_DATA_DIR alone does not stop Terraform discovering terraform.tfstate
    in its working directory. A source-only working copy prevents that migration
    path altogether while preserving relative local module/chart/asset paths.
    """
    source = ROOT / "infrastructure/terraform"
    destination = account_directory(config) / "configuration/infrastructure/terraform"
    copied = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if not path.is_file() or any(part.startswith(".terraform") for part in relative.parts[:-1]):
            continue
        allowed = (path.name.endswith((".tf", ".tf.json", ".tftest.hcl", ".yaml", ".yml", ".tpl", ".sh"))
                   or path.name == ".terraform.lock.hcl"
                   or path.name == "aws-load-balancer-controller-v2.14.1-iam-policy.json"
                   or ("assets" in relative.parts and path.suffix == ".json"))
        if not allowed:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.add(relative.as_posix())
    manifest = account_directory(config) / "configuration-files.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else []
    for relative in set(previous) - copied:
        obsolete = (destination / relative).resolve()
        if not obsolete.is_relative_to(destination.resolve()):
            raise RuntimeError("Invalid generated configuration path")
        obsolete.unlink(missing_ok=True)
    manifest.write_text(json.dumps(sorted(copied), indent=2) + "\n", encoding="utf-8")


def verify_identity(config):
    result = subprocess.run(["aws", "sts", "get-caller-identity", "--profile", config["profile"],
                             "--region", config["region"], "--output", "json"],
                            env=environment(config), capture_output=True, text=True, check=True)
    identity = json.loads(result.stdout)
    if identity["Account"] != config["account_id"]:
        raise RuntimeError(f"Account mismatch: expected {config['account_id']}, got {identity['Account']}")
    return identity


def variables(config, root):
    result = {"expected_account_id": config["account_id"], "aws_region": config["region"]}
    if root != "phase8-dns":
        result.update(deployment_approved=False, project_name="smarttraffic-phase8")
    if root == "phase8-dns":
        result.update(existing_hosted_zone_id=None, certificate_enabled=False)
    if root == "phase8":
        # These explicit values override any old root terraform.tfvars file.
        # Real administrator/DNS/certificate inputs require the next preflight.
        result.update(admin_cidrs=[], public_dns_name="api.smarttrafficmgmt.online",
                      route53_zone_id="NEW_ACCOUNT_ZONE_REQUIRED",
                      public_certificate_arn=f"arn:aws:acm:{config['region']}:{config['account_id']}:certificate/NEW_ACCOUNT_CERTIFICATE_REQUIRED",
                      lambda_zip_path=str(ROOT / ".data/phase6/alert-service.zip"),
                      emr_jar_path=str(ROOT / "services/congestion-processor/target-emr/congestion-processor-1.0.0.jar"))
    return result


def configure(config):
    account_directory(config)  # Validate before constructing paths.
    verify_identity(config)
    if config.get("state_layout") == "existing":
        # Check account-bearing ARNs without displaying any state contents.
        for root in ROOTS:
            path = state_directory(config, root) / "terraform.tfstate"
            if path.exists():
                owners = set(re.findall(r"arn:aws:[^:\s\"]*:[^:\s\"]*:([0-9]{12}):", path.read_text(encoding="utf-8-sig")))
                if owners - {config["account_id"]}:
                    raise RuntimeError("Existing Terraform state contains another account's resource ARNs")
    for root in (() if config.get("state_layout") == "existing" else ROOTS):
        directory = account_directory(config) / root
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "account.tfvars.json"
        # Never overwrite later reviewed DNS/runtime inputs on re-selection.
        if not path.exists():
            path.write_text(json.dumps(variables(config, root), indent=2) + "\n", encoding="utf-8")
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    SELECTION.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def terraform_command(config, root, operation):
    directory = state_directory(config, root)
    working = working_directory(config, root)
    command = ["terraform", f"-chdir={working}"]
    if operation == "init":
        command += ["init", "-input=false", "-reconfigure",
                    f"-backend-config=path={directory / 'terraform.tfstate'}",
                    f"-backend-config=workspace_dir={directory / 'workspaces'}"]
        plugins = ROOT / "infrastructure/terraform" / root / ".terraform/providers"
        if not plugins.is_dir():
            plugins = ROOT / "infrastructure/terraform/phase8/.terraform/providers"
        if plugins.is_dir():
            command.append(f"-plugin-dir={plugins}")
    elif operation == "plan":
        if root == "phase8" or config.get("state_layout") == "existing":
            raise RuntimeError("Planning needs reviewed account inputs, existing-state/resource inventory, quota and cost preflight first")
        command += ["plan", "-input=false", f"-var-file={directory / 'account.tfvars.json'}"]
    elif operation == "output":
        command += ["output", "-json"]
    elif operation == "state-list":
        command += ["state", "list"]
    elif operation == "validate":
        command += ["validate"]
    else:
        raise ValueError("Only read-only preparation operations are supported")
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure")
    setup.add_argument("--profile", required=True)
    setup.add_argument("--account-id", required=True)
    setup.add_argument("--region", default="ap-south-1")
    setup.add_argument("--use-existing-state", action="store_true", help="Reuse the preserved original root states after verifying their account ownership.")
    commands.add_parser("status")
    tf = commands.add_parser("terraform")
    tf.add_argument("root", choices=ROOTS)
    tf.add_argument("operation", choices=("init", "validate", "plan", "output", "state-list"))
    args = parser.parse_args()
    if args.command == "configure":
        config = {"profile": args.profile, "account_id": args.account_id, "region": args.region}
        if args.use_existing_state:
            config["state_layout"] = "existing"
        configure(config)
        print(f"Selected account {config['account_id']} through {config['profile']}; old state preserved")
        return
    config = json.loads(SELECTION.read_text(encoding="utf-8"))
    verify_identity(config)
    if args.command == "status":
        print(json.dumps({**config, "state_directories": {root: str(state_directory(config, root)) for root in ROOTS}}, indent=2))
        return
    command = terraform_command(config, args.root, args.operation)
    if config.get("state_layout") != "existing":
        sync_configuration(config)
    if args.operation == "state-list" and not (state_directory(config, args.root) / "terraform.tfstate").exists():
        print("No local state file exists for this new account/root; no resources are tracked here.")
        return
    subprocess.run(command, env=environment(config, args.root), cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
