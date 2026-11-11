"""Explicit local Kafka/archive setup. Never creates AWS resources or deletes volumes."""
import argparse
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".data/phase3/local.env"


def configure():
    if not CONFIG.exists():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(f"LOCAL_S3_ACCESS_KEY=local-{secrets.token_hex(8)}\n"
                          f"LOCAL_S3_SECRET_KEY={secrets.token_hex(24)}\n", encoding="utf-8")
    print("Local-only credentials configured in ignored .data/phase3/local.env (values not displayed)")


def local_environment():
    if not CONFIG.is_file():
        raise RuntimeError("Run scripts/phase3_local.py configure first")
    values = dict(line.split("=", 1) for line in CONFIG.read_text().splitlines() if line and not line.startswith("#"))
    return {"ARCHIVE_MODE": "local", "ARCHIVE_ENDPOINT_URL": "http://127.0.0.1:8333",
            "ARCHIVE_LOCAL_ACCESS_KEY": values["LOCAL_S3_ACCESS_KEY"],
            "ARCHIVE_LOCAL_SECRET_KEY": values["LOCAL_S3_SECRET_KEY"],
            "ARCHIVE_BUCKET": "traffic-archive", "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:9092",
            "KAFKA_AUTH_MODE": "local", "KAFKA_RAW_TOPIC": "traffic.raw"}


def compose(*arguments):
    if not CONFIG.exists():
        raise RuntimeError("Run configure first")
    subprocess.run(["docker", "compose", "-p", "smarttraffic-phase3", "--env-file", str(CONFIG),
                    "-f", str(ROOT / "infrastructure/local/phase3/compose.yaml"), *arguments],
                   cwd=ROOT, check=True)


def bootstrap():
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    from confluent_kafka.admin import AdminClient, NewTopic
    env = local_environment()
    s3 = boto3.client("s3", endpoint_url=env["ARCHIVE_ENDPOINT_URL"],
                      aws_access_key_id=env["ARCHIVE_LOCAL_ACCESS_KEY"],
                      aws_secret_access_key=env["ARCHIVE_LOCAL_SECRET_KEY"], region_name="us-east-1",
                      config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0},
                                    s3={"addressing_style": "path"}, proxies={}))
    admin = AdminClient({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "socket.timeout.ms": 2000})
    deadline = time.monotonic() + 90
    while True:
        try:
            admin.list_topics(timeout=2)
            s3.list_buckets()
            break
        except Exception:
            if time.monotonic() > deadline:
                raise RuntimeError("Local dependencies did not become ready within 90 seconds")
            time.sleep(1)
    try:
        s3.head_bucket(Bucket=env["ARCHIVE_BUCKET"])
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        s3.create_bucket(Bucket=env["ARCHIVE_BUCKET"])
    topic = NewTopic("traffic.raw", num_partitions=1, replication_factor=1,
                     config={"retention.ms": "86400000", "cleanup.policy": "delete", "min.insync.replicas": "1"})
    future = admin.create_topics([topic], request_timeout=10)["traffic.raw"]
    try:
        future.result(timeout=15)
    except Exception as error:
        from confluent_kafka import KafkaError
        if not error.args or not hasattr(error.args[0], "code") or error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise
    from confluent_kafka.admin import ConfigResource, ResourceType
    resource = ConfigResource(ResourceType.TOPIC, "traffic.raw")
    configuration = admin.describe_configs([resource])[resource].result(timeout=10)
    metadata = admin.list_topics("traffic.raw", timeout=5).topics["traffic.raw"]
    if (metadata.error or len(metadata.partitions) != 1 or
            any(len(partition.replicas) != 1 for partition in metadata.partitions.values()) or
            configuration["retention.ms"].value != "86400000" or
            configuration["cleanup.policy"].value != "delete" or
            configuration["min.insync.replicas"].value != "1"):
        raise RuntimeError("Existing local traffic.raw configuration does not match Phase 3; review it without deleting data")
    print("Bootstrapped real local traffic.raw topic and traffic-archive bucket; no AWS calls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["configure", "up", "down", "restart", "bootstrap", "status"])
    command = parser.parse_args().command
    if command == "configure":
        configure()
    elif command == "bootstrap":
        bootstrap()
    elif command == "up":
        compose("up", "-d")
    elif command == "down":
        compose("down")  # Retains named volumes; no destructive -v option.
    elif command == "status":
        compose("ps")
    else:
        compose("restart")
