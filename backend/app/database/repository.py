"""Repository: all database reads and writes in one place.

Routes call these functions instead of writing queries themselves, which keeps
the routes short and makes a future switch of database painless.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Alert, AnalysisRun, AnomalyRecord, AppSetting, Dataset, MetricSample, MonitoredMachine, utcnow,
)

METRIC_FIELDS = (
    "cpu_percent", "memory_percent", "disk_percent", "disk_read_bytes_per_sec", "disk_write_bytes_per_sec",
    "net_sent_bytes_per_sec", "net_recv_bytes_per_sec", "process_count",
)


# --------------------------------------------------------------------------
# Datasets and analyses
# --------------------------------------------------------------------------

def create_dataset(db: Session, **fields) -> Dataset:
    dataset = Dataset(**fields)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def list_datasets(db: Session) -> list[Dataset]:
    return list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc())))


def get_dataset(db: Session, dataset_id: int) -> Dataset | None:
    return db.get(Dataset, dataset_id)


def delete_dataset(db: Session, dataset: Dataset) -> None:
    db.delete(dataset)
    db.commit()


def latest_analysis(db: Session, dataset_id: int) -> AnalysisRun | None:
    return db.scalars(
        select(AnalysisRun).where(AnalysisRun.dataset_id == dataset_id).order_by(AnalysisRun.id.desc()).limit(1)
    ).first()


def save_analysis(db: Session, dataset: Dataset, results: dict, records: list[dict], config: dict,
                  duration: float) -> AnalysisRun:
    run = AnalysisRun(
        dataset_id=dataset.id,
        duration_seconds=duration,
        config=config,
        results=results,
        domain=results["domain"]["detected"],
        domain_level=results["domain"]["level"],
        risk_level=results["risk"].get("level") if results["risk"].get("available") else None,
        flagged_rows=results["anomalies"]["flagged_rows"],
        finding_count=len(results["findings"]),
    )
    db.add(run)
    db.flush()  # assigns run.id without ending the transaction
    if records:
        db.execute(insert(AnomalyRecord), [
            {"analysis_id": run.id, "row_number": record["row_number"], "deviation": record["deviation"],
             "time": record.get("time"), "methods": record["methods"], "columns": record["columns"],
             "reasons": record["reasons"], "values": record["values"]}
            for record in records
        ])
    db.commit()
    db.refresh(run)
    return run


def anomaly_records(db: Session, analysis_id: int) -> list[AnomalyRecord]:
    return list(db.scalars(select(AnomalyRecord).where(AnomalyRecord.analysis_id == analysis_id)))


def overview(db: Session) -> dict:
    datasets = db.scalar(select(func.count(Dataset.id))) or 0
    analyses = db.scalar(select(func.count(AnalysisRun.id))) or 0
    latest_ids = select(func.max(AnalysisRun.id)).group_by(AnalysisRun.dataset_id)
    latest_runs = list(db.scalars(select(AnalysisRun).where(AnalysisRun.id.in_(latest_ids))))
    domains: dict[str, int] = {}
    for run in latest_runs:
        domains[run.domain] = domains.get(run.domain, 0) + 1
    recent_runs = list(db.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(8)))
    recent_uploads = list(db.scalars(select(Dataset).order_by(Dataset.id.desc()).limit(8)))
    activity = [
        {"type": "analysis", "time": run.created_at, "dataset_id": run.dataset_id,
         "dataset": run.dataset.original_filename, "detail": f"{run.domain}, {run.flagged_rows} flagged row(s)"}
        for run in recent_runs
    ] + [
        {"type": "upload", "time": dataset.created_at, "dataset_id": dataset.id,
         "dataset": dataset.original_filename, "detail": f"{dataset.row_count:,} rows"}
        for dataset in recent_uploads
    ]
    activity.sort(key=lambda item: item["time"], reverse=True)
    latest = recent_runs[0] if recent_runs else None
    return {
        "datasets": datasets,
        "analyses": analyses,
        "total_flagged_rows": sum(run.flagged_rows for run in latest_runs),
        "domain_distribution": domains,
        "latest_analysis": None if latest is None else {
            "id": latest.id, "dataset_id": latest.dataset_id, "dataset": latest.dataset.original_filename,
            "created_at": latest.created_at, "domain": latest.domain, "risk_level": latest.risk_level,
            "flagged_rows": latest.flagged_rows, "finding_count": latest.finding_count,
            "headline": latest.results.get("summary", {}).get("headline"),
        },
        "recent_activity": activity[:10],
    }


def expired_datasets(db: Session, retention_days: int) -> list[Dataset]:
    if retention_days <= 0:
        return []
    cutoff = utcnow() - timedelta(days=retention_days)
    return list(db.scalars(select(Dataset).where(Dataset.created_at < cutoff)))


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def get_setting(db: Session, key: str) -> dict | None:
    setting = db.get(AppSetting, key)
    return setting.value if setting else None


def put_setting(db: Session, key: str, value: dict) -> None:
    setting = db.get(AppSetting, key)
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


# --------------------------------------------------------------------------
# Monitoring
# --------------------------------------------------------------------------

def upsert_machine(db: Session, machine_id: str, hostname: str, interval: int, agent_version: str) -> MonitoredMachine:
    machine = db.scalars(select(MonitoredMachine).where(MonitoredMachine.machine_id == machine_id)).first()
    now = utcnow()
    if machine is None:
        machine = MonitoredMachine(machine_id=machine_id, first_seen=now)
        db.add(machine)
    machine.hostname = hostname
    machine.interval_seconds = interval
    machine.agent_version = agent_version
    machine.last_seen = now
    return machine


def insert_samples(db: Session, machine_id: str, samples: list[dict]) -> tuple[int, int]:
    """Insert samples, skipping timestamps already stored. Returns (inserted, duplicates)."""
    unique: dict[datetime, dict] = {}
    for sample in samples:
        unique.setdefault(sample["timestamp"], sample)
    duplicates = len(samples) - len(unique)
    if not unique:
        return 0, duplicates
    existing = set(db.scalars(
        select(MetricSample.timestamp).where(
            MetricSample.machine_id == machine_id,
            MetricSample.timestamp >= min(unique), MetricSample.timestamp <= max(unique),
        )
    ))
    rows = [{"machine_id": machine_id, **sample} for ts, sample in unique.items() if ts not in existing]
    duplicates += len(unique) - len(rows)
    if not rows:
        return 0, duplicates
    # Plain commit/rollback (no savepoints): SQLite's default Python driver does not
    # handle savepoints reliably, and this works identically on PostgreSQL.
    try:
        db.execute(insert(MetricSample), rows)
        db.commit()
        return len(rows), duplicates
    except IntegrityError:
        # Another request stored some of these at the same moment: retry one by one.
        db.rollback()
    inserted = 0
    for row in rows:
        try:
            db.execute(insert(MetricSample), [row])
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()
            duplicates += 1
    return inserted, duplicates


def list_machines(db: Session) -> list[MonitoredMachine]:
    return list(db.scalars(select(MonitoredMachine).order_by(MonitoredMachine.machine_id)))


def get_machine(db: Session, machine_id: str) -> MonitoredMachine | None:
    return db.scalars(select(MonitoredMachine).where(MonitoredMachine.machine_id == machine_id)).first()


def latest_sample(db: Session, machine_id: str) -> MetricSample | None:
    return db.scalars(
        select(MetricSample).where(MetricSample.machine_id == machine_id)
        .order_by(MetricSample.timestamp.desc()).limit(1)
    ).first()


def samples_since(db: Session, machine_id: str, since: datetime, limit: int = 20_000) -> list[MetricSample]:
    rows = db.scalars(
        select(MetricSample).where(MetricSample.machine_id == machine_id, MetricSample.timestamp >= since)
        .order_by(MetricSample.timestamp.desc()).limit(limit)
    )
    return list(reversed(list(rows)))


def recent_values(db: Session, machine_id: str, field: str, limit: int) -> list[float]:
    column = getattr(MetricSample, field)
    rows = db.scalars(
        select(column).where(MetricSample.machine_id == machine_id, column.is_not(None))
        .order_by(MetricSample.timestamp.desc()).limit(limit)
    )
    return [float(value) for value in rows]


def last_alert(db: Session, machine_id: str, metric: str, kind: str) -> Alert | None:
    return db.scalars(
        select(Alert).where(Alert.machine_id == machine_id, Alert.metric == metric, Alert.kind == kind)
        .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(1)
    ).first()


def add_alert(db: Session, **fields) -> Alert:
    alert = Alert(**fields)
    db.add(alert)
    return alert


def list_alerts(db: Session, machine_id: str | None, limit: int) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)
    if machine_id:
        query = query.where(Alert.machine_id == machine_id)
    return list(db.scalars(query))


def purge_old_metrics(db: Session, retention_days: int) -> int:
    cutoff = utcnow() - timedelta(days=retention_days)
    result = db.execute(delete(MetricSample).where(MetricSample.timestamp < cutoff))
    db.execute(delete(Alert).where(Alert.created_at < cutoff))
    db.commit()
    return result.rowcount or 0
