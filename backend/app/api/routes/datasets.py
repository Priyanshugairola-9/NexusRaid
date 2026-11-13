"""Dataset endpoints: upload, list, inspect, delete."""

import logging

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import require_access_key
from app.database import repository as repo
from app.database.connection import get_db
from app.services.monitoring_service import iso
from app.services.profiling import prepare_and_profile
from app.services.validation import DatasetValidationError, UploadLimits, check_extension, read_and_validate_csv
from app.utils.file_utils import generate_stored_filename, resolve_stored_path, safe_display_name

logger = logging.getLogger("nexusraid")
router = APIRouter(prefix="/datasets", tags=["datasets"], dependencies=[Depends(require_access_key)])
CHUNK_BYTES = 1024 * 1024


def dataset_out(dataset, db: Session) -> dict:
    latest = repo.latest_analysis(db, dataset.id)
    return {
        "id": dataset.id,
        "original_filename": dataset.original_filename,
        "size_bytes": dataset.size_bytes,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "encoding": dataset.encoding,
        "delimiter": dataset.delimiter,
        "upload_warnings": dataset.upload_warnings or [],
        "created_at": iso(dataset.created_at),
        "latest_analysis": None if latest is None else {
            "id": latest.id, "created_at": iso(latest.created_at), "domain": latest.domain,
            "domain_level": latest.domain_level, "risk_level": latest.risk_level,
            "flagged_rows": latest.flagged_rows, "finding_count": latest.finding_count,
        },
    }


def get_dataset_or_404(db: Session, dataset_id: int):
    dataset = repo.get_dataset(db, dataset_id)
    if dataset is None:
        raise AppError(404, "dataset_not_found", f"Dataset {dataset_id} does not exist.")
    return dataset


def remove_file(settings: Settings, stored_filename: str) -> None:
    try:
        resolve_stored_path(settings.upload_dir, stored_filename).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Could not delete stored file %s", stored_filename)


def purge_expired(db: Session, settings: Settings) -> None:
    for dataset in repo.expired_datasets(db, settings.dataset_retention_days):
        remove_file(settings, dataset.stored_filename)
        repo.delete_dataset(db, dataset)


@router.post("/upload", status_code=201)
def upload_dataset(file: UploadFile = File(...), db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> dict:
    display_name = safe_display_name(file.filename)
    check_extension(display_name)
    stored = generate_stored_filename()
    path = resolve_stored_path(settings.upload_dir, stored)
    written = 0
    try:
        # Stream to disk in 1 MB chunks and stop as soon as the limit is passed,
        # instead of trusting the size the browser claims.
        with path.open("wb") as output:
            while chunk := file.file.read(CHUNK_BYTES):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise DatasetValidationError(
                        "file_too_large", f"The file exceeds the {settings.max_upload_mb} MB upload limit.", 413)
                output.write(chunk)
        limits = UploadLimits(settings.max_upload_bytes, settings.max_rows, settings.max_columns)
        validated = read_and_validate_csv(path, limits)
        profile, _ = prepare_and_profile(validated.frame, written)
        dataset = repo.create_dataset(
            db, original_filename=display_name, stored_filename=stored, size_bytes=written,
            row_count=len(validated.frame), column_count=len(validated.frame.columns),
            encoding=validated.encoding, delimiter=validated.delimiter, profile=profile,
            upload_warnings=validated.warnings,
        )
    except Exception:
        path.unlink(missing_ok=True)  # never keep files that failed validation
        raise
    purge_expired(db, settings)
    return dataset_out(dataset, db)


@router.get("")
def list_datasets(db: Session = Depends(get_db)) -> list[dict]:
    return [dataset_out(dataset, db) for dataset in repo.list_datasets(db)]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, db: Session = Depends(get_db)) -> dict:
    return dataset_out(get_dataset_or_404(db, dataset_id), db)


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: int, db: Session = Depends(get_db)) -> dict:
    return get_dataset_or_404(db, dataset_id).profile


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> Response:
    dataset = get_dataset_or_404(db, dataset_id)
    remove_file(settings, dataset.stored_filename)
    repo.delete_dataset(db, dataset)
    return Response(status_code=204)
