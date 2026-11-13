"""Analysis endpoints: run an analysis, read results, explore anomalies, settings."""

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ANALYSIS_SETTINGS_KEY, load_analysis_config
from app.api.routes.datasets import get_dataset_or_404
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import require_access_key
from app.database import repository as repo
from app.database.connection import get_db
from app.schemas.dataset_schema import AnalysisSettingsIn, AnalyzeRequest
from app.services.analysis_config import AnalysisConfig
from app.services.monitoring_service import iso
from app.services.pipeline import run_analysis
from app.services.profiling import prepare_and_profile
from app.services.validation import load_stored_csv
from app.utils.file_utils import resolve_stored_path

router = APIRouter(tags=["analysis"], dependencies=[Depends(require_access_key)])
SORT_KEYS = {"deviation", "row_number", "time"}


def analysis_out(run) -> dict:
    return {"id": run.id, "dataset_id": run.dataset_id, "created_at": iso(run.created_at),
            "duration_seconds": run.duration_seconds, "results": run.results}


def latest_or_404(db: Session, dataset_id: int):
    run = repo.latest_analysis(db, dataset_id)
    if run is None:
        raise AppError(404, "not_analyzed", "This dataset has not been analysed yet.")
    return run


@router.post("/datasets/{dataset_id}/analyze", status_code=201)
def analyze_dataset(dataset_id: int, body: AnalyzeRequest | None = None,
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    dataset = get_dataset_or_404(db, dataset_id)
    config = load_analysis_config(db, body.config if body else None)
    path = resolve_stored_path(settings.upload_dir, dataset.stored_filename)
    if not path.exists():
        raise AppError(410, "file_missing", "The uploaded file is no longer stored on the server. Upload it again.")
    started = time.perf_counter()
    raw = load_stored_csv(path, dataset.encoding, dataset.delimiter)
    profile, frame = prepare_and_profile(raw, dataset.size_bytes)
    outcome = run_analysis(profile, frame, config)
    duration = round(time.perf_counter() - started, 3)
    run = repo.save_analysis(db, dataset, outcome.results, outcome.records, config.to_dict(), duration)
    return analysis_out(run)


@router.get("/datasets/{dataset_id}/results")
def get_results(dataset_id: int, db: Session = Depends(get_db)) -> dict:
    get_dataset_or_404(db, dataset_id)
    return analysis_out(latest_or_404(db, dataset_id))


@router.get("/datasets/{dataset_id}/anomalies")
def get_anomalies(
    dataset_id: int,
    column: str | None = Query(default=None, max_length=255),
    method: str | None = Query(default=None, max_length=40),
    sort: str = Query(default="deviation"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    get_dataset_or_404(db, dataset_id)
    if sort not in SORT_KEYS:
        raise AppError(422, "invalid_sort", f"sort must be one of {sorted(SORT_KEYS)}")
    run = latest_or_404(db, dataset_id)
    records = repo.anomaly_records(db, run.id)
    # At most a few thousand records per analysis, so filtering in Python keeps
    # the query identical for SQLite and PostgreSQL.
    if column:
        records = [record for record in records if column in record.columns]
    if method:
        records = [record for record in records if method in record.methods]
    records.sort(key=lambda record: (getattr(record, sort) is None, getattr(record, sort) or 0),
                 reverse=(order == "desc"))
    page = records[offset: offset + limit]
    return {
        "analysis_id": run.id, "total": len(records), "offset": offset, "limit": limit,
        "items": [{"row_number": r.row_number, "deviation": r.deviation, "time": r.time, "methods": r.methods,
                   "columns": r.columns, "reasons": r.reasons, "values": r.values} for r in page],
    }


@router.get("/settings/analysis")
def get_analysis_settings(db: Session = Depends(get_db)) -> dict:
    return {"config": load_analysis_config(db).to_dict(), "defaults": AnalysisConfig().to_dict()}


@router.put("/settings/analysis")
def put_analysis_settings(body: AnalysisSettingsIn, db: Session = Depends(get_db)) -> dict:
    try:
        config = AnalysisConfig.from_dict(body.config)
    except (ValueError, TypeError) as exc:
        raise AppError(422, "invalid_config", str(exc)) from exc
    repo.put_setting(db, ANALYSIS_SETTINGS_KEY, config.to_dict())
    return {"config": config.to_dict(), "defaults": AnalysisConfig().to_dict()}
