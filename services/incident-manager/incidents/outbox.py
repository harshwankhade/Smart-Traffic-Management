"""Claim and deliver incident alerts without losing committed incident changes."""

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update

from .models import AlertOutboxRow

LOG = logging.getLogger(__name__)


def claim_one(session, *, now=None, lease_seconds=30):
    now = now or datetime.now(UTC)
    candidates = session.scalars(
        select(AlertOutboxRow).where(AlertOutboxRow.sent_at.is_(None),
                                     or_(AlertOutboxRow.lease_until.is_(None),
                                         AlertOutboxRow.lease_until <= now))
        .order_by(AlertOutboxRow.created_at).limit(10)).all()
    for row in candidates:
        token = str(uuid4())
        result = session.execute(
            update(AlertOutboxRow).where(
                AlertOutboxRow.alert_id == row.alert_id,
                AlertOutboxRow.sent_at.is_(None),
                or_(AlertOutboxRow.lease_until.is_(None), AlertOutboxRow.lease_until <= now))
            .values(lease_token=token, lease_until=now + timedelta(seconds=lease_seconds),
                    attempt_count=AlertOutboxRow.attempt_count + 1)
            .execution_options(synchronize_session=False))
        session.commit()
        if result.rowcount:
            return row.alert_id, token, json.loads(row.request_json)
    return None


def finish(session, alert_id, token, *, error=None):
    values = {"lease_token": None,
              "lease_until": datetime.now(UTC) + timedelta(seconds=2) if error else None,
              "last_error": error[:128] if error else None}
    if error is None:
        values["sent_at"] = datetime.now(UTC)
    result = session.execute(update(AlertOutboxRow).where(
        AlertOutboxRow.alert_id == alert_id, AlertOutboxRow.lease_token == token,
        AlertOutboxRow.sent_at.is_(None)).values(**values).execution_options(synchronize_session=False))
    session.commit()
    return bool(result.rowcount)


def deliver_one(database, sender, *, now=None, lease_seconds=30):
    with database.sessions() as session:
        claimed = claim_one(session, now=now, lease_seconds=lease_seconds)
    if not claimed:
        return False
    alert_id, token, request = claimed
    try:
        sender.send(request)
    except Exception as exc:
        LOG.warning("incident alert send failed alert_id=%s error=%s", alert_id, type(exc).__name__)
        with database.sessions() as session:
            finish(session, alert_id, token, error=type(exc).__name__)
        return False
    with database.sessions() as session:
        if not finish(session, alert_id, token):
            LOG.warning("incident alert acknowledgement lost lease alert_id=%s", alert_id)
            return False
    return True


class OutboxWorker:
    def __init__(self, database, sender):
        self.database, self.sender = database, sender
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="incident-alert-outbox", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def _run(self):
        delay = 0.5
        while not self.stop_event.is_set():
            try:
                delivered = deliver_one(self.database, self.sender)
                delay = 0.5 if delivered else min(delay * 2, 5)
            except Exception as exc:
                LOG.warning("incident outbox unavailable error=%s", type(exc).__name__)
                delay = min(delay * 2, 5)
            self.stop_event.wait(delay)
