"""Start and bootstrap persistent loopback-only DynamoDB Local for Phase 5."""

import argparse
import subprocess
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infrastructure/local/phase5/compose.yaml"
TABLES = ("traffic_recommendations", "traffic_window_summaries", "traffic_recovery_events")


def local_client():
    return boto3.client("dynamodb", endpoint_url="http://127.0.0.1:8000",
                        region_name="ap-south-1", aws_access_key_id="local",
                        aws_secret_access_key="local",
                        config=Config(connect_timeout=2, read_timeout=3,
                                      retries={"max_attempts": 0}, proxies={}))


def compose(*args):
    subprocess.run(["docker", "compose", "-p", "smarttraffic-phase5", "-f",
                    str(COMPOSE), *args], cwd=ROOT, check=True)


def bootstrap():
    client = local_client()
    deadline = time.monotonic() + 90
    while True:
        try:
            client.list_tables()
            break
        except (ConnectionClosedError, EndpointConnectionError):
            if time.monotonic() >= deadline:
                raise RuntimeError("DynamoDB Local did not become ready within 90 seconds")
            time.sleep(1)
    for name in TABLES:
        recovery = name == "traffic_recovery_events"
        partition = "publisher_id" if recovery else "intersection_id"
        sort = "recovery_key" if recovery else "window_key"
        try:
            description = client.describe_table(TableName=name)["Table"]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
            description = client.create_table(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[{"AttributeName": partition, "AttributeType": "S"},
                                      {"AttributeName": sort, "AttributeType": "S"}],
                KeySchema=[{"AttributeName": partition, "KeyType": "HASH"},
                           {"AttributeName": sort, "KeyType": "RANGE"}])["TableDescription"]
        expected = [(partition, "HASH"), (sort, "RANGE")]
        actual = [(item["AttributeName"], item["KeyType"]) for item in description["KeySchema"]]
        if actual != expected:
            raise RuntimeError(f"Existing {name} has a different key schema; no table was changed")
        print(f"{name}: {description['TableStatus']}, approved keys verified")
    print("DynamoDB Local bootstrap complete; no AWS calls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "status", "bootstrap"))
    command = parser.parse_args().command
    if command == "up":
        compose("up", "-d")
    elif command == "down":
        compose("down")  # Retains the named volume.
    elif command == "status":
        compose("ps")
    else:
        bootstrap()


if __name__ == "__main__":
    main()
