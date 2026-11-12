"""SQS batch entry point for the existing serverless Alert Service."""

import argparse
import json
import logging

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "contracts/python"))

from alerts import AlertRepository, validate_request

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def process_batch(event, repository):
    if not isinstance(event, dict) or not isinstance(event.get("Records"), list):
        raise ValueError("expected an SQS Records batch")
    failed = []
    for record in event["Records"]:
        if not isinstance(record, dict) or not isinstance(record.get("messageId"), str) or not record["messageId"]:
            raise ValueError("SQS record lacks messageId; cannot report an individual failure")
        message_id = record["messageId"]
        request = None
        try:
            if record.get("eventSource") != "aws:sqs" or not isinstance(record.get("body"), str):
                raise ValueError("invalid SQS record")
            if len(record["body"].encode("utf-8")) > 262144:
                raise ValueError("alert request exceeds size limit")
            request = validate_request(json.loads(record["body"]))
            outcome = repository.put(request)
            LOG.info("alert_id=%s source_type=%s source_id=%s message_id=%s outcome=%s",
                     request["alert_id"], request["source_type"], request["source_id"],
                     message_id, outcome)
        except Exception as exc:
            failed.append({"itemIdentifier": message_id})
            LOG.warning("alert_id=%s source_type=%s source_id=%s message_id=%s outcome=failed error=%s",
                        request["alert_id"] if request else "unknown",
                        request["source_type"] if request else "unknown",
                        request["source_id"] if request else "unknown",
                        message_id, type(exc).__name__)
    return {"batchItemFailures": failed}


def handler(event, context):
    if event == {"scaffold_smoke": True}:
        return {"service": "alert-service", "status": "ok", "scope": "scaffold"}
    return process_batch(event, AlertRepository())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(handler({"scaffold_smoke": True}, None)))
