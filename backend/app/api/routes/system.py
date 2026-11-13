"""Application information and dashboard overview."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import __version__
from app.analyzers.registry import supported_domains
from app.core.config import Settings, get_settings
from app.core.security import require_access_key
from app.database import repository as repo
from app.database.connection import get_db
from app.services.monitoring_service import iso

router = APIRouter(tags=["system"])

PRIVACY_NOTICE = (
    "Uploaded CSV files are stored on this server's disk and their profiles and analysis results in its "
    "database, until you delete the dataset{retention}. Files are not sent to any third party or AI service; "
    "all analysis runs on this server. Do not upload passwords, personal identifiers or confidential data "
    "you are not allowed to share."
)


@router.get("/info")
def info(settings: Settings = Depends(get_settings)) -> dict:
    """Public: lets the frontend know limits and whether an access key is required."""
    retention = (f" or {settings.dataset_retention_days} days pass" if settings.dataset_retention_days else "")
    return {
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "access_key_required": bool(settings.access_key),
        "monitoring_ingestion_enabled": bool(settings.agent_token),
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows,
                   "max_columns": settings.max_columns},
        "retention": {"dataset_days": settings.dataset_retention_days,
                      "metric_days": settings.metric_retention_days},
        "domains": supported_domains(),
        "privacy_notice": PRIVACY_NOTICE.format(retention=retention),
    }


@router.get("/overview", dependencies=[Depends(require_access_key)])
def overview(db: Session = Depends(get_db)) -> dict:
    data = repo.overview(db)
    if data["latest_analysis"]:
        data["latest_analysis"]["created_at"] = iso(data["latest_analysis"]["created_at"])
    for item in data["recent_activity"]:
        item["time"] = iso(item["time"])
    return data
