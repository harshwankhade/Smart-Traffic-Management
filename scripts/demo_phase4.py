"""Real Kafka -> Flink -> results verification, including retained-checkpoint recovery.

Direct Kafka inputs isolate the processor; Phase 3 separately proves HTTP/gRPC.
Only the job created here is canceled. Topic records and volumes are retained.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

from confluent_kafka import Consumer, Producer, TopicPartition
from jsonschema import Draft202012Validator, FormatChecker
from phase3_local import ROOT
from phase4_local import api, compose, submit, wait_ready, bootstrap


def records(topic, seconds=2):
    consumer = Consumer({"bootstrap.servers": "127.0.0.1:9092", "group.id": "phase4-verifier-" + uuid4().hex,
                         "enable.auto.commit": False, "allow.auto.create.topics": False})
    found = []
    try:
        low, _ = consumer.get_watermark_offsets(TopicPartition(topic, 0), timeout=10)
        consumer.assign([TopicPartition(topic, 0, low)])
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            item = consumer.poll(.2)
            if item and item.error():
                raise RuntimeError(str(item.error()))
            if item:
                found.append({"key": item.key().decode() if item.key() else None, "value": json.loads(item.value())})
    finally:
        consumer.close()
    return found


def wait_results(prefix, minimum):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        found = [r for r in records("traffic.results", 1) if r["value"]["intersection_id"].startswith(prefix)]
        if len({r["key"] for r in found}) >= minimum:
            return found
        jobs = api("jobs/overview")["jobs"]
        if any(j["state"] == "FAILED" for j in jobs):
            raise RuntimeError("Flink failed: " + json.dumps(api("jobs/" + next(j["jid"] for j in jobs if j["state"] == "FAILED") + "/exceptions")))
        time.sleep(1)
    raise TimeoutError("Expected results did not arrive; inspect Flink logs and watermarks")


def metric_total(job, name):
    total = 0
    for vertex in api("jobs/" + job)["vertices"]:
        path = "jobs/" + job + "/vertices/" + vertex["id"] + "/subtasks/0/metrics"
        metrics = api(path)
        for metric in metrics:
            if metric["id"].endswith("." + name) or metric["id"] == name:
                total += int(api(path + "?get=" + metric["id"])[0]["value"])
    return total


def run():
    bootstrap()
    # Choose a fresh event-time minute after retained topic data, keeping each run independent.
    previous = records("traffic.raw")
    timestamps = [datetime.fromisoformat(r["value"]["observed_at"].replace("Z", "+00:00"))
                  for r in previous if "observed_at" in r["value"]]
    base = max([datetime(2026, 11, 10, 10, tzinfo=timezone.utc), *timestamps]).replace(second=0, microsecond=0) + timedelta(minutes=2)
    prefix = "p4-" + uuid4().hex[:10]
    samples = []
    producer = Producer({"bootstrap.servers": "127.0.0.1:9092", "enable.idempotence": True, "acks": "all"})
    def reading(id, intersection, seconds, **measurements):
        return {"schema_version": "1.0", "event_id": prefix + "-" + id, "sensor_id": "processor-test-sensor",
                "intersection_id": prefix + "-" + intersection,
                "observed_at": (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"), **measurements}
    def send(*values):
        errors = []
        for value in values:
            producer.produce("traffic.raw", key=value["intersection_id"], value=json.dumps(value),
                             on_delivery=lambda e, m: errors.append(str(e)) if e else None)
            samples.append(value)
        assert producer.flush(15) == 0 and not errors, errors
    job = None
    try:
        job = submit()
        a = reading("a", "main", 0, vehicle_count=2, average_speed=10, occupancy=.4)
        b = reading("b", "main", 59.999999, vehicle_count=3, average_speed=30, occupancy=.8)
        pending = reading("pending", "main", 60, average_speed=45)
        send(a, a, b, reading("other", "other", 30, vehicle_count=7), pending,
             reading("advance1", "watermark", 72, vehicle_count=0))
        first = wait_results(prefix, 2)
        # Once the first window is emitted, a new event targeting it must be excluded.
        send(reading("late", "main", 20, average_speed=0))
        deadline = time.monotonic() + 20
        while metric_total(job, "late_readings") < 1:
            if time.monotonic() > deadline:
                raise AssertionError("Late-data counter did not increase")
            time.sleep(.5)
        assert metric_total(job, "duplicate_readings") >= 1
        checkpoint_after = time.time() * 1000
        deadline = time.monotonic() + 60
        while True:
            checkpoint = api("jobs/" + job + "/checkpoints").get("latest", {}).get("completed")
            if checkpoint and checkpoint["trigger_timestamp"] >= checkpoint_after:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("No checkpoint completed after pending state and late-data check")
            time.sleep(1)
        restore = checkpoint["external_path"]
        print("PASS known first windows, duplicate suppression and late exclusion; checkpoint", checkpoint["id"])
        compose("exec", "-T", "jobmanager", "/opt/flink/bin/flink", "cancel", job)
        job = None
        compose("restart")
        wait_ready()
        job = submit(restore)
        restored = api("jobs/" + job + "/checkpoints").get("latest", {}).get("restored")
        assert restored and restored["external_path"] == restore, restored
        send(a, pending, reading("new", "main", 70, average_speed=35), reading("advance2", "watermark", 132, vehicle_count=0))
        found = wait_results(prefix, 4) # first two windows + main/watermark second windows
        validator = Draft202012Validator(json.loads((ROOT / "contracts/v1/result.schema.json").read_text()), format_checker=FormatChecker())
        logical = {}
        for record in found:
            validator.validate(record["value"])
            assert record["key"] == record["value"]["window_id"]
            if record["key"] in logical:
                assert logical[record["key"]] == record["value"], "conflicting result on replay"
            logical[record["key"]] = record["value"]
        main = sorted([r for r in logical.values() if r["intersection_id"] == prefix + "-main"], key=lambda r: r["window_start"])
        assert len(main) == 2, main
        expected = [dict(reading_count=2, vehicle_count_sum=5, average_speed=20, average_occupancy=.6, congestion="medium"),
                    dict(reading_count=2, vehicle_count_sum=None, average_speed=40, average_occupancy=None, congestion="low")]
        for actual, wanted in zip(main, expected):
            assert {k: actual[k] for k in wanted} == wanted, (actual, wanted)
        other = next(r for r in logical.values() if r["intersection_id"] == prefix + "-other")
        assert other["congestion"] == "unknown" and other["vehicle_count_sum"] == 7
        # Flink's REST metric fetcher is cached; allow its next refresh after recovery.
        deadline = time.monotonic() + 25
        while metric_total(job, "duplicate_readings") < 2:
            if time.monotonic() > deadline:
                raise AssertionError("Restored duplicate counter missing: " + str(metric_total(job, "duplicate_readings")))
            time.sleep(1)
        evidence = {"scope": "real_local_flink_kafka_only", "managed_cloud_verified": False, "flink_image": "flink:2.2.0-scala_2.12-java17",
                    "run_prefix": prefix, "input_records": samples, "expected_main": expected, "actual_results": list(logical.values()),
                    "result_record_count": len(found), "duplicate_results": len(found) - len(logical),
                    "restored_checkpoint": restore, "restored_checkpoint_id": checkpoint["id"], "checkpoint_restoration_confirmed": True}
        print(json.dumps(evidence, indent=2))
        return evidence
    finally:
        if job:
            compose("exec", "-T", "jobmanager", "/opt/flink/bin/flink", "cancel", job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    evidence = run()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
