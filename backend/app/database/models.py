"""Database tables.

Uploaded files stay on disk; the database stores metadata, profiles,
analysis results and monitoring data.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


def utcnow() -> datetime:
    """Current UTC time without tz marker (stored the same way in SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    encoding: Mapped[str] = mapped_column(String(20))
    delimiter: Mapped[str] = mapped_column(String(2))
    profile: Mapped[dict] = mapped_column(JSON)
    upload_warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    analyses: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True, order_by="AnalysisRun.id"
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON)
    domain: Mapped[str] = mapped_column(String(30))
    domain_level: Mapped[str] = mapped_column(String(10))
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    flagged_rows: Mapped[int] = mapped_column(Integer)
    finding_count: Mapped[int] = mapped_column(Integer)

    dataset: Mapped[Dataset] = relationship(back_populates="analyses")
    anomalies: Mapped[list["AnomalyRecord"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )


class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    deviation: Mapped[float] = mapped_column(Float)
    time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    methods: Mapped[list] = mapped_column(JSON)
    columns: Mapped[list] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON)
    values: Mapped[dict] = mapped_column(JSON)

    analysis: Mapped[AnalysisRun] = relationship(back_populates="anomalies")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MonitoredMachine(Base):
    __tablename__ = "monitored_machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(100), unique=True)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    agent_version: Mapped[str] = mapped_column(String(20), default="")
    interval_seconds: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (UniqueConstraint("machine_id", "timestamp", name="uq_sample_machine_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(100), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_read_bytes_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_write_bytes_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_sent_bytes_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_recv_bytes_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    process_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(100), index=True)
    metric: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))  # threshold | statistical | heartbeat
    severity: Mapped[str] = mapped_column(String(10))  # warning | critical
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
