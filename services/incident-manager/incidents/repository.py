from datetime import UTC, datetime
from uuid import uuid4

from .models import IncidentRow


class InvalidTransition(Exception):
    pass


def get(session, identifier):
    return session.get(IncidentRow, identifier)


def create(session, fields):
    now = datetime.now(UTC)
    row = IncidentRow(**fields, event_id=str(uuid4()), status="open",
                      reported_at=now, updated_at=now)
    session.add(row)
    session.commit()
    return row


def update(session, row, fields):
    if row.status == "resolved" and fields.get("status") == "open":
        raise InvalidTransition("Resolved incidents cannot be reopened")
    changed = any(getattr(row, key) != value for key, value in fields.items())
    if changed:
        for key, value in fields.items():
            setattr(row, key, value)
        row.event_id = str(uuid4())
        row.updated_at = datetime.now(UTC)
        session.commit()
    return row
