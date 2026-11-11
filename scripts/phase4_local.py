"""Operate only the local Phase 4 Flink cluster; retain checkpoint volumes."""
import argparse
import json
import subprocess
import time
from urllib.request import urlopen
from phase3_local import ROOT, compose as phase3_compose, bootstrap as phase3_bootstrap


def compose(*args, capture=False):
    return subprocess.run(["docker", "compose", "-p", "smarttraffic-phase4", "-f",
                           str(ROOT / "infrastructure/local/phase4/compose.yaml"), *args],
                          cwd=ROOT, check=True, text=True, capture_output=capture)


def api(path):
    with urlopen("http://127.0.0.1:8081/" + path, timeout=5) as response:
        return json.load(response)


def wait_ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if api("overview")["slots-total"] >= 1:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("Local Flink cluster was not ready in 90 seconds")


def bootstrap():
    from confluent_kafka.admin import AdminClient, NewTopic, ConfigResource, ResourceType
    from confluent_kafka import KafkaException
    admin = AdminClient({"bootstrap.servers": "127.0.0.1:9092"})
    request = admin.create_topics([NewTopic("traffic.results", 1, 1, config={
        "retention.ms": "86400000", "cleanup.policy": "delete", "min.insync.replicas": "1"})])
    try:
        request["traffic.results"].result(20)
    except KafkaException as e:
        if e.args[0].name() != "TOPIC_ALREADY_EXISTS":
            raise
    topic = admin.list_topics("traffic.results", timeout=10).topics["traffic.results"]
    assert len(topic.partitions) == 1 and len(topic.partitions[0].replicas) == 1
    resource = ConfigResource(ResourceType.TOPIC, "traffic.results")
    configs = admin.describe_configs([resource])[resource].result(10)
    for key, value in {"retention.ms": "86400000", "cleanup.policy": "delete", "min.insync.replicas": "1"}.items():
        if configs[key].value != value:
            raise RuntimeError("Existing results topic has unexpected " + key + "; no data/config was overwritten")


def submit(checkpoint=None):
    wait_ready()
    active = [j for j in api("jobs/overview")["jobs"] if j["state"] not in ("FINISHED", "FAILED", "CANCELED")]
    if active:
        raise RuntimeError("A Phase 4 job is already active; do not overlap processors")
    args = ["exec", "-T", "jobmanager", "/opt/flink/bin/flink", "run", "-d"]
    if checkpoint:
        args.extend(["-s", checkpoint])
    args.extend(["-c", "com.smarttraffic.FlinkJob", "/opt/flink/usrlib/traffic.jar"])
    compose(*args)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = api("jobs/overview")["jobs"]
        if any(j["state"] == "RUNNING" for j in jobs):
            return next(j["jid"] for j in jobs if j["state"] == "RUNNING")
        if jobs and jobs[0]["state"] == "FAILED":
            raise RuntimeError("Flink submission failed: " + json.dumps(api("jobs/" + jobs[0]["jid"] + "/exceptions")))
        time.sleep(1)
    raise TimeoutError("Flink job did not reach RUNNING")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "down", "status", "submit", "bootstrap"])
    parser.add_argument("--restore", help="Explicit retained checkpoint/savepoint URI; never silently discard state")
    args = parser.parse_args()
    if args.command == "up":
        try:
            jobs = api("jobs/overview")["jobs"]
        except (OSError, ValueError):
            jobs = []
        if any(j["state"] not in ("FINISHED", "FAILED", "CANCELED") for j in jobs):
            raise RuntimeError("Stop/checkpoint the existing Phase 4 job before recreating its containers")
        phase3_compose("up", "-d")
        phase3_bootstrap()
        bootstrap()
        compose("up", "-d", "--force-recreate")
        wait_ready()
    elif args.command == "submit":
        print("RUNNING", submit(args.restore))
    elif args.command == "bootstrap":
        bootstrap()
    elif args.command == "down":
        compose("down")
    else:
        print(json.dumps(api("jobs/overview"), indent=2))
