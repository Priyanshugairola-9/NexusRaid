"""Live monitoring endpoints.

POST /monitoring/metrics is called by the monitoring agent (X-Agent-Token).
The GET endpoints feed the Live Monitoring page (X-Access-Key if configured).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import load_analysis_config
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import require_access_key, require_agent_token
from app.database import repository as repo
from app.database.connection import get_db
from app.schemas.monitoring_schema import MetricBatchIn
from app.services import monitoring_service as service

router = APIRouter(prefix="/monitoring", tags=["monitoring"])
MACHINE_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"


@router.post("/metrics", dependencies=[Depends(require_agent_token)])
def ingest_metrics(batch: MetricBatchIn, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> dict:
    return service.ingest(db, batch, settings, load_analysis_config(db))


@router.get("/status", dependencies=[Depends(require_access_key)])
def monitoring_status(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    return {"ingestion_enabled": bool(settings.agent_token),
            "machines": service.status(db, settings, load_analysis_config(db))}


@router.get("/metrics", dependencies=[Depends(require_access_key)])
def metric_history(machine_id: str = Query(pattern=MACHINE_PATTERN), minutes: int = Query(default=60, ge=1, le=10_080),
                   db: Session = Depends(get_db)) -> dict:
    if repo.get_machine(db, machine_id) is None:
        raise AppError(404, "machine_not_found", f"No agent has reported as '{machine_id}'.")
    return {"machine_id": machine_id, "minutes": minutes, "samples": service.metric_history(db, machine_id, minutes)}


@router.get("/alerts", dependencies=[Depends(require_access_key)])
def alert_history(machine_id: str | None = Query(default=None, pattern=MACHINE_PATTERN),
                  limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    return {"alerts": service.alerts(db, machine_id, limit)}


@router.get("/analysis", dependencies=[Depends(require_access_key)])
def analyze_machine(machine_id: str = Query(pattern=MACHINE_PATTERN), hours: int = Query(default=6, ge=1, le=168),
                    db: Session = Depends(get_db)) -> dict:
    if repo.get_machine(db, machine_id) is None:
        raise AppError(404, "machine_not_found", f"No agent has reported as '{machine_id}'.")
    result = service.analyze_history(db, machine_id, hours, load_analysis_config(db))
    if result is None:
        raise AppError(409, "not_enough_data",
                       f"At least {service.MIN_ANALYSIS_SAMPLES} samples in the last {hours} h are needed.")
    return result
