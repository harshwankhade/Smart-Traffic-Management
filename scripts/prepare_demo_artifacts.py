"""Prepare reusable binaries before starting billable runtime resources.

Default: local build/cache only. --build-bucket enables remote cache reads;
--upload explicitly permits writes to an already Terraform-owned build bucket.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".data/phase8-artifacts"
JAR = ROOT / "services/congestion-processor/target-emr/congestion-processor-1.0.0.jar"
ZIP = ROOT / ".data/phase6/alert-service.zip"


def fingerprint(paths):
    files = set()
    for relative in paths:
        path = ROOT / relative
        for candidate in ([path] if path.is_file() else path.rglob("*")):
            if candidate.is_file() and not set(candidate.relative_to(ROOT).parts) & {
                    "__pycache__", "target", "target-emr", ".pytest_cache"} and candidate.suffix != ".pyc":
                files.add(candidate)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def binary_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_revision():
    # The Dockerfile copies every service, so every copied source affects the key.
    return fingerprint([".dockerignore", "infrastructure/container", "requirements-lock.txt", "contracts", "services"])


def cached(manifest, revision, outputs):
    return (manifest.get("revision") == revision and
            all(path.is_file() and manifest.get("sha256", {}).get(name) == binary_hash(path)
                for name, path in outputs.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maven", help="Path to mvn/mvn.cmd, otherwise use PATH or the project-local Maven.")
    parser.add_argument("--build-bucket")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Use only existing Maven dependencies.")
    args = parser.parse_args()
    if args.upload and not args.build_bucket:
        parser.error("--upload requires --build-bucket from the retained Terraform state")
    revision = fingerprint(["services/congestion-processor", "services/alert-service",
                            "contracts/python", "requirements-lock.txt", "scripts/build_phase6_lambda.py"])
    outputs = {"processor.jar": JAR, "alerts.zip": ZIP}
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest_path = CACHE / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    s3 = None
    prefix = f"builds/{revision}"
    if args.build_bucket:
        import boto3
        from botocore.exceptions import ClientError
        s3 = boto3.Session(profile_name=os.getenv("AWS_PROFILE"),
                           region_name=os.getenv("AWS_REGION", "ap-south-1")).client("s3")
        if not cached(manifest, revision, outputs):
            try:
                response = s3.get_object(Bucket=args.build_bucket, Key=f"{prefix}/manifest.json")
                body = response["Body"]
                try:
                    manifest = json.loads(body.read())
                finally:
                    body.close()
                if manifest.get("revision") != revision:
                    raise RuntimeError("remote build revision mismatch")
                for name, path in outputs.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    s3.download_file(args.build_bucket, f"{prefix}/{name}", str(path))
                if not cached(manifest, revision, outputs):
                    raise RuntimeError("remote build checksum mismatch")
            except ClientError as error:
                if error.response["Error"]["Code"] not in ("NoSuchKey", "404"):
                    raise
    if not cached(manifest, revision, outputs):
        maven = args.maven or shutil.which("mvn")
        if not maven:
            local = ROOT / ".data/tooling/apache-maven-3.9.11/bin/mvn.cmd"
            if local.is_file():
                maven = str(local)
        if not maven:
            raise RuntimeError("Maven is required for a cache miss; supply --maven")
        command = [maven, f"-Dmaven.repo.local={ROOT / '.data/m2'}"]
        if args.offline:
            command.append("-o")
        subprocess.run([*command, "-f", "services/congestion-processor/pom.xml", "-P", "emr", "package"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/build_phase6_lambda.py", "build"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "scripts/build_phase6_lambda.py", "check"], cwd=ROOT, check=True)
        manifest = {"revision": revision, "sha256": {name: binary_hash(path) for name, path in outputs.items()}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if args.upload:
        for name, path in outputs.items():
            s3.upload_file(str(path), args.build_bucket, f"{prefix}/{name}",
                           ExtraArgs={"ServerSideEncryption": "AES256"})
        # Publish the manifest only after both binaries have been uploaded.
        s3.put_object(Bucket=args.build_bucket, Key=f"{prefix}/manifest.json",
                      Body=manifest_path.read_bytes(), ServerSideEncryption="AES256")
    print(f"Binaries ready: {revision}. Unchanged inputs reuse cached builds.")


if __name__ == "__main__":
    main()
