"""Deterministic synthetic readings; supporting tool, not an application service."""
import argparse
import json
import random
from datetime import UTC, datetime, timedelta


def generate(count=5, seed=12, sensor_id="sensor-demo", intersection_id="int-demo", prefix="demo"):
    rng = random.Random(seed)
    start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    return [{"schema_version": "1.0", "event_id": f"{prefix}-{index:04d}",
             "sensor_id": sensor_id, "intersection_id": intersection_id,
             "observed_at": (start + timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
             "vehicle_count": rng.randrange(0, 30), "average_speed": round(rng.uniform(5, 60), 2),
             "occupancy": round(rng.uniform(0, 1), 3)} for index in range(count)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--seed", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.count <= 10000:
        parser.error("count must be between 1 and 10000")
    for reading in generate(args.count, args.seed):
        print(json.dumps(reading))
