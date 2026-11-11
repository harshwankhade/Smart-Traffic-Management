"""Bootstrap the Phase 6 alert table in existing loopback DynamoDB Local."""

import argparse

from botocore.exceptions import ClientError
from phase5_local import compose, local_client


def bootstrap():
    client = local_client()
    name = "traffic_alerts"
    try:
        description = client.describe_table(TableName=name)["Table"]
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        description = client.create_table(
            TableName=name, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "alert_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "alert_id", "KeyType": "HASH"}])["TableDescription"]
    if [(key["AttributeName"], key["KeyType"]) for key in description["KeySchema"]] != [("alert_id", "HASH")]:
        raise RuntimeError("existing traffic_alerts table has different keys")
    print(f"{name}: {description['TableStatus']}, alert_id key verified; no AWS calls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "bootstrap"))
    command = parser.parse_args().command
    if command == "bootstrap":
        bootstrap()
    else:
        compose("up", "-d") if command == "up" else compose("down")
