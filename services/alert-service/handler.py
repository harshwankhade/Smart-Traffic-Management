"""Local smoke entry point, not a queue-processing Lambda implementation."""

import argparse
import json


def handler(event, context):
    if event != {"scaffold_smoke": True}:
        raise ValueError("Phase 1 supports only the explicit scaffold smoke event")
    return {"service": "alert-service", "status": "ok", "scope": "scaffold"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(handler({"scaffold_smoke": True}, None)))
