from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="incident_manager")


class IncidentRow(Base):
    __tablename__ = "incidents"
    __table_args__ = (CheckConstraint("status IN ('open', 'resolved')"),
                      CheckConstraint("type IN ('collision', 'closure', 'disruption')"))
    incident_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intersection_id: Mapped[str] = mapped_column(String(128))
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    __mapper_args__ = {"version_id_col": version}


class AlertOutboxRow(Base):
    __tablename__ = "alert_outbox"
    alert_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incident_manager.incidents.incident_id"))
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(128))
