"""Statically render and validate the Phase 8 GitOps tree; never contacts a cluster."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "deploy" / "gitops" / "apps"
SERVICES = ("sensor-registry", "traffic-ingestion", "event-publisher",
            "signal-recommendation", "incident-manager", "traffic-analytics")


def run(*command: str, stdin: str | None = None) -> str:
    result = subprocess.run(command, input=stdin, text=True, capture_output=True,
                            cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def main() -> None:
    root_application = (ROOT / "deploy" / "gitops" / "bootstrap" / "smarttraffic-root.yaml").read_text(encoding="utf-8")
    for fragment in ("kind: Application", "prune: true", "selfHeal: true", "path: deploy/gitops/apps"):
        if fragment not in root_application:
            raise RuntimeError(f"root Application lacks {fragment!r}")
    rendered = run("kubectl", "kustomize", str(APPS))
    for service in SERVICES:
        for required in (f"name: {service}", f"app: {service}"):
            if required not in rendered:
                raise RuntimeError(f"rendered manifests lack {required!r}")
    if "kind: StatefulSet" not in rendered or "name: smarttraffic-zookeeper" not in rendered:
        raise RuntimeError("ZooKeeper GitOps Application is absent")
    if "REPLACE_WITH_ACM_CERTIFICATE_ARN" not in rendered or "REPLACE_WITH_PUBLIC_DNS_NAME" not in rendered:
        raise RuntimeError("public ingress placeholders were unexpectedly removed")
    print("PASS GitOps manifests rendered; root ownership, all six services, ZooKeeper and deliberate deployment placeholders were verified locally.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
