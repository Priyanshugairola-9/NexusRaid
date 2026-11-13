"""Shapes of the data sent by the monitoring agent. Pydantic rejects anything else with a 422."""

from datetime import datetime

from pydantic import BaseModel, Field


class MetricSampleIn(BaseModel):
    timestamp: datetime = Field(description="When the sample was taken (ISO 8601 with time zone).")
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_percent: float | None = Field(default=None, ge=0, le=100)
    disk_percent: float | None = Field(default=None, ge=0, le=100)
    disk_read_bytes_per_sec: float | None = Field(default=None, ge=0)
    disk_write_bytes_per_sec: float | None = Field(default=None, ge=0)
    net_sent_bytes_per_sec: float | None = Field(default=None, ge=0)
    net_recv_bytes_per_sec: float | None = Field(default=None, ge=0)
    process_count: int | None = Field(default=None, ge=0)


class MetricBatchIn(BaseModel):
    machine_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    hostname: str = Field(default="", max_length=255)
    agent_version: str = Field(default="", max_length=20)
    interval_seconds: int = Field(ge=1, le=3600)
    samples: list[MetricSampleIn] = Field(min_length=1, max_length=500)
