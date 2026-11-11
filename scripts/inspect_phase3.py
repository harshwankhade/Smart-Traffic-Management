"""Consume actual local Kafka records or fetch an actual archived object."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from phase3_local import ROOT, local_environment

sys.path.insert(0, str(ROOT / "contracts/python"))
sys.path.insert(0, str(ROOT / "services/event-publisher"))
from traffic_contracts.reading import archive_key
from publisher.adapters import S3Archive, kafka_config
from confluent_kafka import Consumer, TopicPartition


def consume(timeout=3):
    consumer = Consumer({**kafka_config(), "group.id": f"phase3-verifier-{uuid4().hex}",
                         "enable.auto.commit": False, "allow.auto.create.topics": False,
                         "auto.offset.reset": "earliest"})
    records = []
    try:
        consumer.assign([TopicPartition(os.environ.get("KAFKA_RAW_TOPIC", "traffic.raw"), 0, 0)])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = consumer.poll(0.2)
            if message and message.error():
                raise RuntimeError(str(message.error()))
            if message:
                records.append({"key": message.key().decode(), "offset": message.offset(),
                                "record": json.loads(message.value())})
    finally:
        consumer.close()
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["consume", "archive"])
    parser.add_argument("--event-id")
    args = parser.parse_args()
    os.environ.update(local_environment())
    if args.command == "archive":
        if not args.event_id:
            parser.error("archive requires --event-id")
        archive = S3Archive()
        try:
            print(archive.read(archive_key(args.event_id)).decode())
        finally:
            archive.close()
    else:
        for record in consume():
            if not args.event_id or record["record"]["event_id"] == args.event_id:
                print(json.dumps(record))
