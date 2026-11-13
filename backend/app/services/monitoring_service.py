"""Live monitoring: store agent metrics, raise alerts, report machine status.

The decision rules live in monitoring_rules.py (pure and unit-tested); this
module connects them to the database.
"""

import time
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database import repository as repo
from app.database.models import utcnow
from app.services import monitoring_rules as rules
from app.services.analysis_config import AnalysisConfig
from app.services.pipeline import run_analysis
from app.services.profiling import prepare_and_profile

FUTURE_TOLERANCE = timedelta(minutes=5)
HISTORY_POINTS = 120
PURGE_EVERY_SECONDS = 3600
MIN_ANALYSIS_SAMPLES = 30
_last_purge = 0.0


def _to_utc_naive(value):
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def iso(value) -> str | None:
    return None if value is None else value.isoformat() + "Z"


def ingest(db: Session, batch, settings: Settings, config: AnalysisConfig) -> dict:
    global _last_purge
    now = utcnow()
    oldest_allowed = now - timedelta(days=settings.metric_retention_days)
    accepted, rejected = [], 0
    for sample in batch.samples:
        data = sample.model_dump()
        data["timestamp"] = _to_utc_naive(data["timestamp"])
        if data["timestamp"] > now + FUTURE_TOLERANCE or data["timestamp"] < oldest_allowed:
            rejected += 1  # clock far off, or older than we keep
            continue
        accepted.append(data)

    repo.upsert_machine(db, batch.machine_id, batch.hostname, batch.interval_seconds, batch.agent_version)
    db.commit()  # the heartbeat is recorded even if no sample is new
    inserted, duplicates = repo.insert_samples(db, batch.machine_id, accepted) if accepted else (0, 0)

    created = []
    if inserted:
        latest = max(accepted, key=lambda item: item["timestamp"])
        history = {
            field: repo.recent_values(db, batch.machine_id, field, HISTORY_POINTS + 1)[1:]
            for field in list(rules.PERCENT_METRICS) + list(rules.RATE_METRICS)
        }
        candidates = rules.threshold_alerts(latest, config.risk_thresholds) + rules.statistical_alerts(
            latest, history, config.spike_threshold)
        for candidate in candidates:
            previous = repo.last_alert(db, batch.machine_id, candidate["metric"], candidate["kind"])
            if rules.should_create(candidate["severity"], previous.created_at if previous else None,
                                   previous.severity if previous else None, now, settings.alert_cooldown_seconds):
                repo.add_alert(db, machine_id=batch.machine_id, **candidate)
                created.append(candidate)
    db.commit()

    if time.monotonic() - _last_purge > PURGE_EVERY_SECONDS:
        _last_purge = time.monotonic()
        repo.purge_old_metrics(db, settings.metric_retention_days)
    return {"accepted": inserted, "duplicates": duplicates, "rejected": rejected, "alerts_created": len(created)}


def _sample_dict(sample) -> dict:
    return {"timestamp": iso(sample.timestamp), **{field: getattr(sample, field) for field in repo.METRIC_FIELDS}}


def status(db: Session, settings: Settings, config: AnalysisConfig) -> list[dict]:
    now = utcnow()
    machines = []
    for machine in repo.list_machines(db):
        latest = repo.latest_sample(db, machine.machine_id)
        timeout = rules.heartbeat_timeout(machine.interval_seconds, settings.heartbeat_grace_factor,
                                          settings.min_heartbeat_timeout_seconds)
        since = (now - machine.last_seen).total_seconds() if machine.last_seen else None
        latest_values = _sample_dict(latest) if latest else None
        state, reasons = rules.machine_state(latest_values, since, timeout, config.risk_thresholds)
        if state == "unknown" and since is not None:
            previous = repo.last_alert(db, machine.machine_id, "heartbeat", "heartbeat")
            if rules.should_create("warning", previous.created_at if previous else None,
                                   previous.severity if previous else None, now, settings.alert_cooldown_seconds):
                repo.add_alert(db, machine_id=machine.machine_id, metric="heartbeat", kind="heartbeat",
                               severity="warning", value=since, message=reasons[0])
        machines.append({
            "machine_id": machine.machine_id, "hostname": machine.hostname, "agent_version": machine.agent_version,
            "interval_seconds": machine.interval_seconds, "first_seen": iso(machine.first_seen),
            "last_seen": iso(machine.last_seen), "seconds_since_seen": round(since, 1) if since is not None else None,
            "heartbeat_timeout_seconds": timeout, "state": state, "reasons": reasons, "latest": latest_values,
        })
    db.commit()
    return machines


def metric_history(db: Session, machine_id: str, minutes: int) -> list[dict]:
    since = utcnow() - timedelta(minutes=minutes)
    return [_sample_dict(sample) for sample in repo.samples_since(db, machine_id, since)]


def alerts(db: Session, machine_id: str | None, limit: int) -> list[dict]:
    return [
        {"id": alert.id, "machine_id": alert.machine_id, "metric": alert.metric, "kind": alert.kind,
         "severity": alert.severity, "message": alert.message, "value": alert.value,
         "created_at": iso(alert.created_at)}
        for alert in repo.list_alerts(db, machine_id, limit)
    ]


def analyze_history(db: Session, machine_id: str, hours: int, config: AnalysisConfig) -> dict | None:
    samples = metric_history(db, machine_id, hours * 60)
    if len(samples) < MIN_ANALYSIS_SAMPLES:
        return None
    profile, frame = prepare_and_profile(rules.history_frame(samples))
    results = run_analysis(profile, frame, config).results
    return {key: results[key] for key in ("summary", "domain", "anomalies", "trends", "risk", "findings")}
