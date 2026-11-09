from sqlalchemy import CheckConstraint, ForeignKey, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(schema="sensor_registry")


class IntersectionRow(Base):
    __tablename__ = "intersections"
    intersection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)


class SensorRow(Base):
    __tablename__ = "sensors"
    __table_args__ = (CheckConstraint("status IN ('active', 'inactive')"),)
    sensor_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intersection_id: Mapped[str] = mapped_column(
        ForeignKey("sensor_registry.intersections.intersection_id"), nullable=False)
    location: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
