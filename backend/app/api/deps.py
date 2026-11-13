"""Shared dependencies for routes."""

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.database import repository as repo
from app.services.analysis_config import AnalysisConfig

ANALYSIS_SETTINGS_KEY = "analysis"


def load_analysis_config(db: Session, overrides: dict | None = None) -> AnalysisConfig:
    """Saved settings, then per-request overrides (nested threshold dicts are merged)."""
    merged = dict(repo.get_setting(db, ANALYSIS_SETTINGS_KEY) or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    try:
        return AnalysisConfig.from_dict(merged)
    except (ValueError, TypeError) as exc:
        raise AppError(422, "invalid_config", str(exc)) from exc
