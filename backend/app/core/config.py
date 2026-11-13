"""Application settings, read from environment variables and backend/.env.

Every setting can be overridden with an environment variable prefixed with
NEXUSRAID_ (for example NEXUSRAID_DATABASE_URL). Local and cloud deployments
run the same code and differ only in these values.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The backend/ folder. This file lives at backend/app/core/config.py.
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUSRAID_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NexusRaid"
    environment: Literal["development", "production"] = "development"

    # Storage. SQLite file by default; a PostgreSQL URL works without code changes.
    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'nexusraid.db').as_posix()}"
    upload_dir: Path = DEFAULT_DATA_DIR / "uploads"

    # Upload limits (kept modest for low-end hardware).
    max_upload_mb: int = Field(default=25, ge=1, le=500)
    max_rows: int = Field(default=200_000, ge=10, le=5_000_000)
    max_columns: int = Field(default=200, ge=2, le=2_000)

    # Retention. 0 = keep datasets until the user deletes them.
    dataset_retention_days: int = Field(default=0, ge=0, le=3650)
    metric_retention_days: int = Field(default=7, ge=1, le=365)

    # Optional shared access key. When set, every data endpoint requires the
    # X-Access-Key header. Strongly recommended for any public deployment.
    access_key: str = ""

    # Token the monitoring agent must send (X-Agent-Token). Empty = ingestion disabled.
    agent_token: str = ""
    heartbeat_grace_factor: float = Field(default=3.0, ge=1.5, le=20)
    min_heartbeat_timeout_seconds: int = Field(default=60, ge=10, le=3600)
    alert_cooldown_seconds: int = Field(default=900, ge=0, le=86_400)

    # Comma-separated frontend origins that are allowed to call the API.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # If this folder contains a built frontend (npm run build), the backend also
    # serves it, so the whole application runs on one port.
    frontend_dist: Path = DEFAULT_FRONTEND_DIST

    @field_validator("upload_dir", "frontend_dist")
    @classmethod
    def _resolve_relative(cls, value: Path) -> Path:
        # Relative paths are taken relative to backend/, not to whichever
        # folder the server happened to be started from.
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create the folders the app writes to, if they do not exist yet."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.removeprefix("sqlite:///")
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings object (read once, reused everywhere)."""
    return Settings()
