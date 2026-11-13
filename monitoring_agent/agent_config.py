"""Agent configuration: JSON file, then environment variables, then command-line flags.

The token should come from the NEXUSRAID_AGENT_TOKEN environment variable, not
from a file that might be committed to Git by accident.
"""

import json
import os
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path

ALL_METRICS = ("cpu", "memory", "disk", "disk_io", "network", "processes")
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


def default_machine_id() -> str:
    return (_SAFE_ID.sub("-", socket.gethostname()).strip("-") or "machine")[:100]


def default_disk_path() -> str:
    return os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"


@dataclass
class AgentConfig:
    api_url: str = "http://127.0.0.1:8000"
    token: str = ""
    machine_id: str = field(default_factory=default_machine_id)
    interval_seconds: int = 15
    metrics: tuple[str, ...] = ALL_METRICS
    disk_path: str = field(default_factory=default_disk_path)
    max_buffer: int = 2000
    timeout_seconds: float = 10.0

    @property
    def endpoint(self) -> str:
        return self.api_url.rstrip("/") + "/api/v1/monitoring/metrics"

    def validate(self) -> None:
        if not self.api_url.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", self.machine_id):
            raise ValueError("machine_id may only contain letters, digits, '.', '_' and '-' (max 100)")
        if not 1 <= self.interval_seconds <= 3600:
            raise ValueError("interval_seconds must be between 1 and 3600")
        unknown = set(self.metrics) - set(ALL_METRICS)
        if unknown:
            raise ValueError(f"Unknown metrics: {', '.join(sorted(unknown))}. Allowed: {', '.join(ALL_METRICS)}")
        if not 10 <= self.max_buffer <= 100_000:
            raise ValueError("max_buffer must be between 10 and 100000")


def load_config(path: str | None = None, overrides: dict | None = None) -> AgentConfig:
    config = AgentConfig()
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, value in data.items():
            if value is None:
                continue
            if not hasattr(config, key):
                raise ValueError(f"Unknown setting '{key}' in {path}")
            setattr(config, key, tuple(value) if key == "metrics" else value)
    environment = {
        "api_url": os.environ.get("NEXUSRAID_API_URL"),
        "token": os.environ.get("NEXUSRAID_AGENT_TOKEN"),
        "machine_id": os.environ.get("NEXUSRAID_MACHINE_ID"),
    }
    for key, value in {**environment, **(overrides or {})}.items():
        if value not in (None, ""):
            setattr(config, key, value)
    config.interval_seconds = int(config.interval_seconds)
    config.validate()
    return config
