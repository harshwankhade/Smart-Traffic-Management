"""Statically render and validate the Phase 8 GitOps tree; never contacts a cluster."""
from __future__ import annotations

import subprocess
import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "deploy" / "gitops" / "apps"
OBSERVABILITY = ROOT / "deploy" / "gitops" / "observability"
SERVICES = ("sensor-registry", "traffic-ingestion", "event-publisher",
            "signal-recommendation", "incident-manager", "traffic-analytics")


def run(*command: str, stdin: str | None = None) -> str:
    result = subprocess.run(command, input=stdin, text=True, capture_output=True,
                            cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account-id", help="Also require certificate and image pins to belong to this AWS account.")
    args = parser.parse_args()
    root_application = (ROOT / "deploy" / "gitops" / "bootstrap" / "smarttraffic-root.yaml").read_text(encoding="utf-8")
    for fragment in ("kind: Application", "prune: true", "selfHeal: true", "path: deploy/gitops/apps"):
        if fragment not in root_application:
            raise RuntimeError(f"root Application lacks {fragment!r}")
    rendered = run("kubectl", "kustomize", str(APPS))
    observability = run("kubectl", "kustomize", str(OBSERVABILITY))
    hpas = run("kubectl", "kustomize", str(ROOT / "deploy/gitops/hpa"))
    for service in SERVICES:
        for required in (f"name: {service}", f"app: {service}"):
            if required not in rendered:
                raise RuntimeError(f"rendered manifests lack {required!r}")
    if "kind: StatefulSet" not in rendered or "name: zookeeper" not in rendered:
        raise RuntimeError("ZooKeeper GitOps Application is absent")
    for required in ("api.smarttrafficmgmt.online", "external-secrets.io/v1",
                     "smarttraffic-runtime-values"):
        if required not in rendered:
            raise RuntimeError(f"rendered manifests lack deployment input {required!r}")
    certificate = re.search(r"arn:aws:acm:ap-south-1:([0-9]{12}):certificate/[0-9a-f-]{36}", rendered)
    if not certificate:
        raise RuntimeError("public ingress lacks a concrete regional ACM certificate ARN")
    if args.expected_account_id:
        if certificate.group(1) != args.expected_account_id:
            raise RuntimeError("certificate belongs to a different account; issue and pin the new account certificate before deployment")
        registries = re.findall(r"([0-9]{12})\.dkr\.ecr\.ap-south-1\.amazonaws\.com/", rendered)
        if len(registries) != 6 or any(account != args.expected_account_id for account in registries):
            raise RuntimeError("all six images must be published and pinned in the expected account")
    for required in ("kind: HorizontalPodAutoscaler", "name: traffic-ingestion", "name: traffic-analytics"):
        if required not in hpas:
            raise RuntimeError(f"HPA manifests lack {required!r}")
    for required in ("kind: StatefulSet", "name: kafka", "kafka.smarttraffic.internal",
                     "publishNotReadyAddresses: true", "external-dns.kubernetes.io/ttl", "KAFKA_AUTH_MODE: tls"):
        if required not in rendered:
            raise RuntimeError(f"private Kafka configuration lacks {required!r}")
    if "loadBalancerClass: service.k8s.aws/nlb" in rendered:
        raise RuntimeError("Kafka must use headless private DNS, not an NLB")
    for required in ("kind: ServiceMonitor",
                     "kind: DaemonSet", "aws-for-fluent-bit"):
        if required not in observability:
            raise RuntimeError(f"observability manifests lack {required!r}")
    print("PASS GitOps manifests rendered; root ownership, six services, ZooKeeper, HTTPS ingress, External Secrets, HPA, Prometheus scraping, and CloudWatch log collection were verified locally.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
