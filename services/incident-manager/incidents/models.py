from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, String, Text
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
