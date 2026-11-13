"""Report downloads: HTML report, JSON results, CSV exports."""

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.routes.analysis import latest_or_404
from app.api.routes.datasets import get_dataset_or_404
from app.core.security import require_access_key
from app.database import repository as repo
from app.database.connection import get_db
from app.services.report_generator import build_anomalies_csv, build_findings_csv, build_html_report

router = APIRouter(prefix="/datasets", tags=["reports"], dependencies=[Depends(require_access_key)])


def _download(content: str, media_type: str, filename: str) -> Response:
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _records(db: Session, run) -> list[dict]:
    rows = repo.anomaly_records(db, run.id)
    rows.sort(key=lambda row: -row.deviation)
    return [{"row_number": r.row_number, "deviation": r.deviation, "time": r.time, "methods": r.methods,
             "columns": r.columns, "reasons": r.reasons, "values": r.values} for r in rows]


@router.get("/{dataset_id}/report")
def report(dataset_id: int, format: str = Query(default="html", pattern="^(html|json)$"),
           db: Session = Depends(get_db)) -> Response:
    dataset = get_dataset_or_404(db, dataset_id)
    run = latest_or_404(db, dataset_id)
    if format == "json":
        payload = {"dataset": {"id": dataset.id, "filename": dataset.original_filename},
                   "profile": dataset.profile, "results": run.results}
        return _download(json.dumps(payload, indent=2), "application/json",
                         f"nexusraid-results-{dataset_id}.json")
    html = build_html_report({"original_filename": dataset.original_filename}, dataset.profile, run.results,
                             _records(db, run))
    return _download(html, "text/html; charset=utf-8", f"nexusraid-report-{dataset_id}.html")


@router.get("/{dataset_id}/anomalies.csv")
def anomalies_csv(dataset_id: int, db: Session = Depends(get_db)) -> Response:
    get_dataset_or_404(db, dataset_id)
    run = latest_or_404(db, dataset_id)
    return _download(build_anomalies_csv(_records(db, run)), "text/csv; charset=utf-8",
                     f"nexusraid-anomalies-{dataset_id}.csv")


@router.get("/{dataset_id}/findings.csv")
def findings_csv(dataset_id: int, db: Session = Depends(get_db)) -> Response:
    get_dataset_or_404(db, dataset_id)
    run = latest_or_404(db, dataset_id)
    return _download(build_findings_csv(run.results["findings"]), "text/csv; charset=utf-8",
                     f"nexusraid-findings-{dataset_id}.csv")
