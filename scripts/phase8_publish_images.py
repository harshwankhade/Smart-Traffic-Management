"""Build, push, and digest-pin the six Phase 8 images after ECR repositories exist.

This script deliberately changes only Git-tracked Kustomize image directives.
Run it after the reviewed ECR-only Terraform stage; commit/push its output before
Argo CD's root Application is installed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

import boto3


ROOT = Path(__file__).resolve().parents[1]
KUSTOMIZATION = ROOT / "deploy" / "gitops" / "apps" / "kustomization.yaml"
SERVICES = ("sensor-registry", "traffic-ingestion", "event-publisher",
            "signal-recommendation", "incident-manager", "traffic-analytics")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repositories-json", required=True,
                        help="JSON object from `terraform output -json ecr_repositories`.")
    parser.add_argument("--tag", default="phase8-run", help="Immutable tag to push once per run.")
    parser.add_argument("--docker-config", help="Isolated Docker config directory for a short-lived registry login.")
    args = parser.parse_args()
    repositories = json.loads(Path(args.repositories_json).read_text(encoding="utf-8"))
    if set(repositories) != set(SERVICES):
        raise SystemExit("repository output must contain exactly the six Phase 8 services")
    region = os.environ.get("AWS_REGION", "ap-south-1")
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"), region_name=region)
    token = session.client("ecr").get_authorization_token()["authorizationData"][0]
    username, password = base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
    if username != "AWS":
        raise RuntimeError("unexpected ECR authorization username")
    registry = token["proxyEndpoint"].removeprefix("https://")
    docker = ["docker"]
    if args.docker_config:
        config_directory = Path(args.docker_config)
        config_directory.mkdir(parents=True, exist_ok=True)
        # Avoid a workstation-wide credential helper; this temporary inline
        # ECR authorization expires and is never written into the repository.
        (config_directory / "config.json").write_text(
            json.dumps({"auths": {registry: {"auth": token["authorizationToken"]}}}) + "\n",
            encoding="utf-8")
        docker.extend(["--config", str(config_directory)])
    else:
        subprocess.run([*docker, "login", "--username", username, "--password-stdin", registry],
                       input=password, text=True, check=True)
    images = []
    ecr = session.client("ecr")
    for service in SERVICES:
        repository_name = repositories[service].split("/", 1)[1]
        try:
            digest = ecr.describe_images(repositoryName=repository_name,
                                         imageIds=[{"imageTag": args.tag}])["imageDetails"][0]["imageDigest"]
            print(f"Reusing existing immutable image {service}@{digest}")
        except ecr.exceptions.ImageNotFoundException:
            local = f"smarttraffic/{service}:{args.tag}"
            remote = f"{repositories[service]}:{args.tag}"
            run(*docker, "build", "-f", "infrastructure/container/Dockerfile",
                "--build-arg", f"SERVICE_DIR=services/{service}", "-t", local, ".")
            run(*docker, "tag", local, remote)
            run(*docker, "push", remote)
            digest = ecr.describe_images(repositoryName=repository_name,
                                         imageIds=[{"imageTag": args.tag}])["imageDetails"][0]["imageDigest"]
        images.append((f"smarttraffic/{service}", repositories[service], digest))
    document = KUSTOMIZATION.read_text(encoding="utf-8").rstrip() + "\n"
    marker = "\nimages:\n"
    document = document.split(marker, 1)[0].rstrip() + "\nimages:\n"
    for name, repository, digest in images:
        document += f"  - name: {name}\n    newName: {repository}\n    digest: {digest}\n"
    KUSTOMIZATION.write_text(document, encoding="utf-8")
    print("Digest-pinned Kustomize images written. Commit and push before Argo CD bootstrap.")


if __name__ == "__main__":
    main()
