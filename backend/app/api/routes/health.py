"""Health check: confirms the backend, its database and its upload folder work.

Hosting platforms call an endpoint like this to decide whether the app is alive.
"""

import logging
import os

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import get_settings
from app.database.connection import get_db
from app.schemas.health_schema import HealthResponse

logger = logging.getLogger("nexusraid")
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()

    try:
        db.execute(text("SELECT 1"))
        database_status = "ok"
    except SQLAlchemyError:
        logger.exception("Health check: database query failed")
        database_status = "unavailable"

    storage_ok = settings.upload_dir.is_dir() and os.access(settings.upload_dir, os.W_OK)
    storage_status = "ok" if storage_ok else "unavailable"

    healthy = database_status == "ok" and storage_status == "ok"
    # 503 tells a hosting platform "running, but not able to serve properly".
    response.status_code = 200 if healthy else 503

    return HealthResponse(
        status="ok" if healthy else "degraded",
        app=settings.app_name,
        version=__version__,
        database=database_status,
        storage=storage_status,
    )
