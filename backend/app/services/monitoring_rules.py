"""Pure rules for live monitoring (no database, no web framework, easy to test).

  threshold alerts   latest CPU / memory / disk % against warning and critical levels
  statistical alerts latest value far outside the machine's own recent behaviour
  cooldown           the same alert is not repeated within the cooldown, unless it got worse
  heartbeat          no data for longer than max(minimum, grace x reporting interval) -> "unknown"
"""

from datetime import datetime

import numpy as np
import pandas as pd

from app.utils.data_utils import robust_center_scale

PERCENT_METRICS = {
    "cpu_percent": ("cpu", "CPU"),
    "memory_percent": ("memory", "Memory"),
    "disk_percent": ("disk", "Disk"),
}
RATE_METRICS = {
    "disk_read_bytes_per_sec": "Disk read rate",
    "disk_write_bytes_per_sec": "Disk write rate",
    "net_sent_bytes_per_sec": "Network send rate",
    "net_recv_bytes_per_sec": "Network receive rate",
}
MIN_HISTORY = 30
MIN_PERCENT_CHANGE = 10.0      # percentage points; smaller jumps are not worth an alert
MIN_RATE_BYTES = 100 * 1024    # 100 KB/s; tiny rates are noise
SEVERITY_RANK = {"warning": 1, "critical": 2}


def threshold_alerts(latest: dict, thresholds: dict) -> list[dict]:
    alerts = []
    for field, (key, label) in PERCENT_METRICS.items():
        value = latest.get(field)
        if value is None or key not in thresholds:
            continue
        warning, critical = thresholds[key]
        if value >= critical:
            severity, level = "critical", critical
        elif value >= warning:
            severity, level = "warning", warning
        else:
            continue
        alerts.append({
            "metric": field, "kind": "threshold", "severity": severity, "value": float(value),
            "message": f"{label} at {value:.1f}% (≥ {severity} level {level:g}%).",
        })
    return alerts


def statistical_alerts(latest: dict, history: dict[str, list[float]], threshold: float) -> list[dict]:
    """Flag the latest value when it is far from the machine's own recent values."""
    alerts = []
    for field in list(PERCENT_METRICS) + list(RATE_METRICS):
        value = latest.get(field)
        past = np.asarray(history.get(field) or [], dtype=float)
        if value is None or past.size < MIN_HISTORY:
            continue
        is_rate = field in RATE_METRICS
        transform = np.log1p if is_rate else (lambda x: x)
        center, scale = robust_center_scale(transform(past))
        if scale == 0:
            continue
        score = (float(transform(value)) - center) / scale
        median = float(np.median(past))
        if score < threshold:
            continue
        if not is_rate and value - median < MIN_PERCENT_CHANGE:
            continue
        if is_rate and (value < MIN_RATE_BYTES or value < 2 * median):
            continue
        label = PERCENT_METRICS[field][1] if field in PERCENT_METRICS else RATE_METRICS[field]
        shown = f"{value:.1f}%" if not is_rate else f"{value / 1_048_576:.2f} MB/s"
        typical = f"{median:.1f}%" if not is_rate else f"{median / 1_048_576:.2f} MB/s"
        alerts.append({
            "metric": field, "kind": "statistical", "severity": "warning", "value": float(value),
            "message": f"{label} {shown} is unusually high for this machine (typical {typical}; "
                       f"{score:.1f} robust SDs above its last {past.size} readings).",
        })
    return alerts


def should_create(candidate_severity: str, last_alert_time: datetime | None, last_severity: str | None,
                  now: datetime, cooldown_seconds: int) -> bool:
    if last_alert_time is None:
        return True
    if SEVERITY_RANK.get(candidate_severity, 0) > SEVERITY_RANK.get(last_severity or "", 0):
        return True  # escalation is always reported
    return (now - last_alert_time).total_seconds() >= cooldown_seconds


def heartbeat_timeout(interval_seconds: int, grace_factor: float, minimum_seconds: int) -> float:
    return max(float(minimum_seconds), grace_factor * interval_seconds)


def machine_state(latest: dict | None, seconds_since_seen: float | None, timeout: float,
                  thresholds: dict) -> tuple[str, list[str]]:
    """normal | warning | critical | unknown (no recent data), with reasons."""
    if latest is None or seconds_since_seen is None:
        return "unknown", ["No data has been received yet."]
    if seconds_since_seen > timeout:
        return "unknown", [f"No data for {seconds_since_seen:.0f} s (expected within {timeout:.0f} s)."]
    state, reasons = "normal", []
    for field, (key, label) in PERCENT_METRICS.items():
        value = latest.get(field)
        if value is None or key not in thresholds:
            continue
        warning, critical = thresholds[key]
        if value >= critical:
            state = "critical"
            reasons.append(f"{label} {value:.1f}% ≥ critical {critical:g}%")
        elif value >= warning:
            if state != "critical":
                state = "warning"
            reasons.append(f"{label} {value:.1f}% ≥ warning {warning:g}%")
    return state, reasons or ["All monitored metrics are below their warning levels."]


def history_frame(samples: list[dict]) -> pd.DataFrame:
    """Turn stored samples into a table the normal analysis pipeline understands.

    Column names such as cpu_percent and net_sent_bytes_per_sec are recognised by
    the server analyzer, so live data is analysed exactly like an uploaded CSV.
    """
    frame = pd.DataFrame(samples)
    frame["timestamp"] = frame["timestamp"].str.replace("Z", "", regex=False)
    return frame.dropna(axis=1, how="all")
