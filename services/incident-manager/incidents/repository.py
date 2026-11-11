from datetime import UTC, datetime
from uuid import uuid4

from traffic_contracts.alerts import canonical_body, incident_request

from .models import AlertOutboxRow, IncidentRow


class InvalidTransition(Exception):
    pass


def get(session, identifier):
    return session.get(IncidentRow, identifier)


def create(session, fields):
    now = datetime.now(UTC)
    row = IncidentRow(**fields, event_id=str(uuid4()), status="open",
                      reported_at=now, updated_at=now)
    session.add(row)
    session.flush()
    queue_alert(session, row)
    session.commit()
    return row


def update(session, row, fields):
    if row.status == "resolved" and fields.get("status") == "open":
        raise InvalidTransition("Resolved incidents cannot be reopened")
    changed = any(getattr(row, key) != value for key, value in fields.items())
    if changed:
        status_changed = "status" in fields and fields["status"] != row.status
        for key, value in fields.items():
            setattr(row, key, value)
        row.event_id = str(uuid4())
        row.updated_at = datetime.now(UTC)
        if status_changed:
            queue_alert(session, row)
        session.commit()
    return row


def queue_alert(session, row):
    request = incident_request(row)
    session.add(AlertOutboxRow(alert_id=request["alert_id"], incident_id=row.incident_id,
                               request_json=canonical_body(request), created_at=datetime.now(UTC)))
