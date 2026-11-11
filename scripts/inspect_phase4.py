"""Read congestion records locally or from a reachable IAM/TLS MSK cluster.

Cloud mode performs only Kafka reads; it needs an explicitly configured bootstrap
address and existing private network access, credentials and verifier policy.
"""
import argparse
import json
import os
import sys
import time
from uuid import uuid4
from phase3_local import ROOT

sys.path.insert(0, str(ROOT / "services/event-publisher"))
from publisher.adapters import kafka_config
from confluent_kafka import Consumer

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="store_true")
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--intersection-prefix", default="")
    args = parser.parse_args()
    if args.cloud:
        if not os.environ.get("KAFKA_BOOTSTRAP_SERVERS"):
            parser.error("Cloud reads require explicit KAFKA_BOOTSTRAP_SERVERS; never fall back to localhost")
        os.environ["KAFKA_AUTH_MODE"] = "iam"
    else:
        os.environ["KAFKA_AUTH_MODE"] = "local"
        os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "127.0.0.1:9092"
    consumer = Consumer({**kafka_config(), "group.id": "phase4-verifier-" + uuid4().hex,
                         "auto.offset.reset": "earliest", "enable.auto.commit": False,
                         "allow.auto.create.topics": False})
    try:
        consumer.subscribe(["traffic.results"])
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            record = consumer.poll(.2)
            if record and record.error():
                raise RuntimeError(str(record.error()))
            if record:
                value = json.loads(record.value())
                if value["intersection_id"].startswith(args.intersection_prefix):
                    print(json.dumps({"key": record.key().decode(), "record": value}))
    finally:
        consumer.close()
