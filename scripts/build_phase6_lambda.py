"""Build and inspect a deterministic Python 3.14 ZIP for Alert Service."""

import argparse
import importlib.metadata
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".data/phase6/alert-service.zip"
SOURCES = {
    "handler.py": ROOT / "services/alert-service/handler.py",
    "alerts.py": ROOT / "services/alert-service/alerts.py",
    "traffic_contracts/__init__.py": ROOT / "contracts/python/traffic_contracts/__init__.py",
    "traffic_contracts/dynamo_store.py": ROOT / "contracts/python/traffic_contracts/dynamo_store.py",
}
PACKAGES = {"boto3": "boto3", "botocore": "botocore", "jmespath": "jmespath",
            "s3transfer": "s3transfer", "python-dateutil": "dateutil",
            "urllib3": "urllib3", "six": "six.py"}


def build():
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("build with Python 3.14 for the approved Lambda runtime")
    site = Path(importlib.metadata.distribution("boto3").locate_file(""))
    files = dict(SOURCES)
    versions = {}
    for distribution, target in PACKAGES.items():
        versions[distribution] = importlib.metadata.version(distribution)
        source = site / target
        if source.is_file():
            files[target] = source
        else:
            if not source.is_dir():
                raise RuntimeError(f"missing local dependency {target}")
            for path in source.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    files[path.relative_to(site).as_posix()] = path
    lock = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    for name, version in versions.items():
        if f"{name}=={version}" not in lock.splitlines():
            raise RuntimeError(f"{name} {version} does not match requirements-lock.txt")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return files, versions


def check():
    if not OUTPUT.is_file():
        raise RuntimeError("Lambda ZIP is absent; run build first")
    with zipfile.ZipFile(OUTPUT) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"corrupt ZIP member: {bad}")
        required = set(SOURCES) | {"boto3/__init__.py", "botocore/__init__.py",
                                   "dateutil/__init__.py", "six.py"}
        if not required.issubset(archive.namelist()):
            raise RuntimeError("Lambda ZIP lacks source or bundled dependencies")
        with tempfile.TemporaryDirectory(prefix="p6-lambda-check-") as directory:
            archive.extractall(directory)
            import subprocess
            code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                    "import handler, boto3, botocore; "
                    "assert handler.handler({'scaffold_smoke': True}, None)['status'] == 'ok'; "
                    "assert all(sys.argv[1] in m.__file__ for m in (handler, boto3, botocore))")
            subprocess.run([sys.executable, "-c", code, directory], check=True, timeout=20)
    return {"zip": str(OUTPUT), "bytes": OUTPUT.stat().st_size, "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    command = parser.parse_args().command
    if command == "build":
        files, versions = build()
        print(json.dumps({"members": len(files), "versions": versions,
                          "package": check()}, sort_keys=True))
    else:
        print(json.dumps(check(), sort_keys=True))
