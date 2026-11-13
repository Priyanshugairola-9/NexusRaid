"""Reusable checks that domain analyzers combine.

Each check either returns a finding (a dict from make_finding) or None, and
records itself in DomainOutput.checks so the user can see what ran, what was
skipped and why.
"""

import math

import numpy as np
import pandas as pd

from app.analyzers.base_analyzer import AnalysisContext, DomainOutput
from app.services.explanation import make_finding
from app.utils.data_utils import format_number, round_or_none

RECENT_FRACTION = 0.10


def time_ordered(ctx: AnalysisContext, column: str, group_column: str | None = None):
    """Yield (group, times_ms, values) sorted by time. Nothing is yielded without a datetime axis."""
    time_column = ctx.time_column
    if time_column is None:
        return
    data = pd.DataFrame({
        "t": (ctx.frame[time_column] - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1),
        "v": pd.to_numeric(ctx.frame[column], errors="coerce"),
    })
    if group_column:
        data["g"] = ctx.frame[group_column].astype(str)
    data = data.dropna(subset=["t"]).sort_values("t", kind="stable")
    if group_column:
        for group, part in data.groupby("g", sort=True):
            yield group, part["t"].to_numpy(), part["v"].to_numpy(dtype=float)
    else:
        yield "all", data["t"].to_numpy(), data["v"].to_numpy(dtype=float)


def format_duration(milliseconds: float) -> str:
    minutes = milliseconds / 60_000
    if minutes < 120:
        return f"{minutes:,.0f} minutes"
    hours = minutes / 60
    return f"{hours:,.1f} hours" if hours < 72 else f"{hours / 24:,.1f} days"


def is_percent_like(ctx: AnalysisContext, column: str) -> bool:
    """True when nearly all values lie in 0..100 (so % thresholds make sense)."""
    values = ctx.numeric(column)
    values = values[np.isfinite(values)]
    return values.size > 0 and np.mean((values >= 0) & (values <= 100)) >= 0.98 and values.max() > 1


def bounds_check(ctx: AnalysisContext, out: DomainOutput, column: str, low: float, high: float,
                 what: str) -> None:
    values = ctx.numeric(column)
    finite = values[np.isfinite(values)]
    outside = (finite < low) | (finite > high)
    out.ran(f"Plausible range of {column}", f"expected {format_number(low)} to {format_number(high)}")
    if not outside.any():
        return
    examples = ", ".join(format_number(value) for value in np.unique(finite[outside])[:5])
    out.findings.append(make_finding(
        source=ctx.domain,
        category="data_quality",
        severity="warning",
        title=f"{int(outside.sum())} impossible value(s) in {column}",
        what_happened=f"{column} should be a {what} between {format_number(low)} and {format_number(high)}, "
                      f"but {int(outside.sum())} value(s) fall outside that range.",
        columns=[column],
        observed=f"Examples: {examples}.",
        comparison=f"Valid range for a {what}: {format_number(low)} to {format_number(high)}.",
        why_flagged="Values outside the physically or logically possible range cannot be correct measurements.",
        method="Range (plausibility) check",
        could_indicate="A data-entry error, unit mix-up, sensor fault or wrong column mapping.",
        confidence="high",
        confidence_basis="Assumes the column really is a " + what + " (inferred from its name).",
        needs="Confirmation of the column's unit and valid range.",
        next_steps="Correct or remove these values at the source before trusting statistics for this column.",
    ))


def sustained_high(ctx: AnalysisContext, out: DomainOutput, column: str, warning: float, critical: float,
                   label: str) -> dict | None:
    """How often and for how long a utilisation metric stayed above its warning level."""
    series = list(time_ordered(ctx, column))
    if not series:
        out.skipped(f"Sustained high {label}", "Needs a date/time column.")
        return None
    _, times, values = series[0]
    keep = np.isfinite(values)
    times, values = times[keep], values[keep]
    if values.size < 10:
        out.skipped(f"Sustained high {label}", "Fewer than 10 measurements.")
        return None
    above = values >= warning
    longest, longest_start, run, run_start = 0, 0, 0, 0
    for i, flag in enumerate(above):
        if flag:
            if run == 0:
                run_start = i
            run += 1
            if run > longest:
                longest, longest_start = run, run_start
        else:
            run = 0
    recent = values[-max(3, int(values.size * RECENT_FRACTION)):]
    state = {
        "column": column,
        "share_above_warning_pct": round(100 * above.mean(), 2),
        "share_above_critical_pct": round(100 * (values >= critical).mean(), 2),
        "longest_run_points": int(longest),
        "recent_median": round_or_none(np.median(recent)),
        "recent_max": round_or_none(recent.max()),
        "warning": warning,
        "critical": critical,
    }
    out.ran(f"Sustained high {label}", f"warning {warning}%, critical {critical}%")
    if longest >= 3:
        duration = times[longest_start + longest - 1] - times[longest_start]
        start_text = pd.Timestamp(times[longest_start], unit="ms").strftime("%Y-%m-%d %H:%M")
        out.findings.append(make_finding(
            source=ctx.domain,
            category="pattern",
            severity="warning" if state["recent_median"] >= warning else "notice",
            title=f"{label} stayed at or above {warning:g}% for {format_duration(duration)}",
            what_happened=f"{column} was at or above the warning level in {state['share_above_warning_pct']}% of "
                          f"measurements; the longest continuous stretch began {start_text}.",
            columns=[column],
            observed=f"Longest run: {longest} consecutive measurements ({format_duration(duration)}). "
                     f"Recent median: {format_number(state['recent_median'])}%.",
            comparison=f"Configured thresholds: warning {warning:g}%, critical {critical:g}%.",
            why_flagged="Short peaks are normal; long stretches near capacity leave little headroom.",
            method="Threshold run-length analysis",
            could_indicate="Sustained load near capacity, which can slow the system or precede saturation.",
            confidence="high",
            confidence_basis="Directly measured against the configured thresholds.",
            needs="Whether these thresholds suit this machine and workload.",
            next_steps="Check which processes or workloads were running during that stretch.",
        ))
    return state


def flatline(ctx: AnalysisContext, out: DomainOutput, column: str, group_column: str | None) -> list[dict]:
    """Find stretches where a sensor repeats exactly the same value (possibly stuck)."""
    runs = []
    for group, times, values in time_ordered(ctx, column, group_column):
        finite = np.isfinite(values)
        if finite.sum() < 20 or np.nanstd(values) == 0:
            continue
        min_run = max(6, int(0.02 * finite.sum()))
        same = np.concatenate([[False], (np.diff(values) == 0) & finite[1:] & finite[:-1]])
        start = None
        for i in range(len(values) + 1):
            if i < len(values) and same[i]:
                if start is None:
                    start = i - 1
            elif start is not None:
                length = i - start
                if length >= min_run:
                    runs.append({"group": group, "start": float(times[start]), "end": float(times[i - 1]),
                                 "points": int(length), "value": round_or_none(values[start])})
                start = None
    out.ran(f"Stuck values in {column}")
    if runs:
        longest = max(runs, key=lambda run: run["points"])
        where = f" ({longest['group']})" if longest["group"] != "all" else ""
        out.findings.append(make_finding(
            source=ctx.domain,
            category="data_quality",
            severity="warning",
            title=f"{column} repeated the same value for long stretches ({len(runs)} time(s))",
            what_happened=f"{column}{where} reported exactly {format_number(longest['value'])} "
                          f"{longest['points']} times in a row, for {format_duration(longest['end'] - longest['start'])}.",
            columns=[column],
            observed=f"{len(runs)} stretch(es) of identical consecutive readings.",
            comparison="Live sensors normally show small fluctuations between readings.",
            why_flagged="A long run of identical values is a common sign of a frozen sensor or a collector "
                        "repeating its last value.",
            method="Run-length analysis of consecutive identical values",
            could_indicate="A stuck or disconnected sensor, or a gateway filling in missing readings.",
            confidence="medium",
            confidence_basis="Some quantities are genuinely stable; this is judged against the sensor's own "
                             "variability elsewhere.",
            needs="Maintenance logs for the device.",
            next_steps="Check the device's connection and readings around that time.",
            evidence={"runs": runs[:10]},
        ))
    return runs


def event_bursts(ctx: AnalysisContext, out: DomainOutput, entity_column: str, bucket: str,
                 entity_label: str, event_label: str) -> list[dict]:
    """Entities with far more events in one time bucket than is normal for this dataset."""
    time_column = ctx.time_column
    name = f"Bursts of {event_label} per {entity_label}"
    if time_column is None:
        out.skipped(name, "Needs a date/time column.")
        return []
    data = pd.DataFrame({"entity": ctx.frame[entity_column].astype(str), "t": ctx.frame[time_column]}).dropna()
    data["bucket"] = data["t"].dt.floor(bucket)
    counts = data.groupby(["entity", "bucket"]).size()
    if counts.empty:
        return []
    q99 = float(np.percentile(counts, 99))
    threshold = max(10, math.ceil(3 * q99))
    bursts = counts[counts >= threshold].sort_values(ascending=False)
    out.ran(name, f"threshold: at least {threshold} {event_label} per {bucket}")
    rows = [
        {"entity": entity, "bucket_start": start.isoformat(), "count": int(count)}
        for (entity, start), count in bursts.head(20).items()
    ]
    if rows:
        top = rows[0]
        out.findings.append(make_finding(
            source=ctx.domain,
            category="pattern",
            severity="notice",
            title=f"Unusual burst: {top['entity']} with {top['count']} {event_label} in one {bucket} window",
            what_happened=f"{len(bursts)} {entity_label}/time window(s) had far more {event_label} than usual.",
            columns=[entity_column, time_column],
            observed=f"Highest: {top['count']} {event_label} from {top['entity']} starting {top['bucket_start']}.",
            comparison=f"99% of {entity_label}/{bucket} windows have at most {q99:g} {event_label}; the burst "
                        f"threshold is {threshold}.",
            why_flagged="Activity concentrated in a short window stands out from the usual rhythm.",
            method="Event counting per entity and time bucket",
            could_indicate="A batch job, a retry loop, a promotion or busy period, or behaviour worth reviewing. "
                           "It is not, by itself, evidence of misuse.",
            confidence="medium",
            confidence_basis="Compared with this dataset's own distribution of per-window counts.",
            needs="Knowledge of scheduled jobs, campaigns or known activity for this entity.",
            next_steps=f"Filter the data to {top['entity']} around that time and review the individual events.",
            evidence={"bursts": rows},
        ))
        out.tables.append({"title": f"Busiest {entity_label} windows ({bucket})",
                           "columns": [entity_label, "window start", event_label],
                           "rows": [[row["entity"], row["bucket_start"], row["count"]] for row in rows[:10]]})
    return rows


def distribution_table(ctx: AnalysisContext, out: DomainOutput, column: str, title: str, limit: int = 8) -> dict:
    counts = ctx.frame[column].astype(str).where(ctx.frame[column].notna()).value_counts()
    total = int(counts.sum())
    rows = [[value, int(count), round(100 * count / total, 2)] for value, count in counts.head(limit).items()]
    out.tables.append({"title": title, "columns": [column, "rows", "% of rows"], "rows": rows})
    return {"top_share": rows[0][2] if rows else 0, "second_share": rows[1][2] if len(rows) > 1 else 0,
            "top": rows[0][0] if rows else None, "distinct": int(counts.size)}


def percentile_metrics(ctx: AnalysisContext, out: DomainOutput, column: str, label: str) -> dict:
    values = ctx.numeric(column)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {}
    p50, p95, p99 = np.percentile(values, [50, 95, 99])
    for name, value in (("median", p50), ("p95", p95), ("p99", p99)):
        out.metrics.append({"label": f"{label} {name}", "value": round_or_none(value, 2), "column": column})
    return {"p50": p50, "p95": p95, "p99": p99}


def recent_vs_overall(ctx: AnalysisContext, mask: np.ndarray) -> dict | None:
    """Compare the share of flagged rows in the most recent 10% of the time span with the whole period."""
    time_column = ctx.time_column
    if time_column is None or mask is None:
        return None
    times = (ctx.frame[time_column] - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)
    valid = times.notna().to_numpy()
    if valid.sum() < 50:
        return None
    t = times.to_numpy(dtype=float)
    cutoff = np.nanmin(t) + (1 - RECENT_FRACTION) * (np.nanmax(t) - np.nanmin(t))
    recent = valid & (t >= cutoff)
    if recent.sum() < 5:
        return None
    overall_rate = mask[valid].mean()
    recent_rate = mask[recent].mean()
    return {"recent_rate": float(recent_rate), "overall_rate": float(overall_rate),
            "recent_rows": int(recent.sum()), "ratio": float(recent_rate / overall_rate) if overall_rate else None}


def linear_projection(ctx: AnalysisContext, out: DomainOutput, column: str, limit: float, label: str) -> None:
    """If a utilisation metric grows steadily, say when the straight line would reach the limit."""
    name = f"Straight-line projection for {label}"
    state = ctx.trends.column_states.get(column) if ctx.trends else None
    result = next((item for item in (ctx.trends.summary.get("results", []) if ctx.trends else [])
                   if item["column"] == column and not item.get("skipped")), None)
    if not state or not result:
        out.skipped(name, "Needs a time axis and enough data.")
        return
    out.ran(name, "only reported for a steady increase with a good linear fit (R² >= 0.8)")
    slope, r_squared, recent = result["slope"], result["r_squared"], result["recent_level"]
    if result["direction"] != "increasing" or not slope or slope <= 0 or (r_squared or 0) < 0.8 or recent >= limit:
        return
    units_left = (limit - recent) / slope
    unit = result["slope_unit"].replace("per ", "")
    out.findings.append(make_finding(
        source=ctx.domain,
        category="trend",
        severity="notice",
        title=f"{label} would reach {limit:g}% in about {units_left:,.0f} {unit}s if the trend continued",
        what_happened=f"{column} has grown steadily ({format_number(slope)} points {result['slope_unit']}).",
        columns=[column],
        observed=f"Recent level {format_number(recent)}%; straight-line fit R² = {r_squared}.",
        comparison=f"Limit: {limit:g}%.",
        why_flagged="A steady, well-fitting increase toward a hard limit is worth planning for.",
        method="Linear extrapolation of the fitted trend",
        could_indicate="Capacity that will run out unless something changes.",
        confidence="low",
        confidence_basis="Assumes the past straight-line growth simply continues. This is an extrapolation, "
                         "not a prediction; clean-ups or workload changes would alter it.",
        needs="Planned changes in data volume or retention.",
        next_steps="Review what is consuming capacity and plan clean-up or expansion before the estimated time.",
    ))


# --------------------------------------------------------------------------
# Risk signals (0 = no concern ... 3 = severe), consumed by the risk engine
# --------------------------------------------------------------------------

def level_signal(state: dict | None, label: str, weight: float = 1.0, near_band: float = 10.0,
                 unit: str = "%") -> dict | None:
    """Score the RECENT level of a metric against absolute warning/critical thresholds.

    near_band: how far below the warning level still counts as "close" (score 1).
    """
    if not state or state.get("recent_median") is None:
        return None
    level, warning, critical = state["recent_median"], state["warning"], state["critical"]
    if level >= critical:
        score, text = 3, f"at or above the critical level ({critical:g}{unit})"
    elif level >= warning:
        score, text = 2, f"above the warning level ({warning:g}{unit})"
    elif level >= warning - near_band:
        score, text = 1, f"close to the warning level ({warning:g}{unit})"
    else:
        score, text = 0, f"well below the warning level ({warning:g}{unit})"
    return {"name": f"{label} level", "column": state["column"], "score": score, "weight": weight,
            "explanation": f"Recent level {format_number(level)}{unit} is {text}."}


def trend_signal(ctx: AnalysisContext, column: str, label: str, worse: str, weight: float = 1.0,
                 max_score: int = 2) -> dict | None:
    """Score how far a metric has moved in its 'worse' direction ("up", "down" or "either").

    A trend or drift shows that a metric is much worse than its own baseline, but not that the
    current level is unacceptable; that needs an absolute threshold. So trends score at most 2
    (elevated); only level_signal with configured thresholds can score 3 (severe).
    """
    state = ctx.trends.column_states.get(column) if ctx.trends else None
    if not state:
        return None
    drift = state["drift_score"] or 0.0
    direction = state["direction"]
    signed = drift if worse == "up" else -drift if worse == "down" else abs(drift)
    bad_direction = (
        (worse == "up" and direction == "increasing")
        or (worse == "down" and direction == "decreasing")
        or (worse == "either" and direction != "stable")
    )
    threshold = ctx.config.drift_threshold
    if signed >= 2 * threshold:
        score = 3
    elif signed >= threshold:
        score = 2
    elif bad_direction:
        score = 1
    else:
        score = 0
    score = min(score, max_score)
    if score == 0:
        text = "no worsening trend or drift"
    else:
        text = (f"{direction} trend" if bad_direction else "no steady trend")
        text += f"; recent level is {abs(drift):.1f} baseline spreads {'above' if drift > 0 else 'below'} the start"
    return {"name": f"{label} trend", "column": column, "score": score, "weight": weight,
            "explanation": text[0].upper() + text[1:] + "."}


def latency_level_signal(ctx: AnalysisContext, column: str, label: str, weight: float = 1.0) -> dict | None:
    """Absolute latency check, only when the user has configured latency_ms thresholds (an SLO)."""
    pair = ctx.config.risk_thresholds.get("latency_ms")
    state = ctx.trends.column_states.get(column) if ctx.trends else None
    if not pair or not state:
        return None
    warning, critical = pair
    return level_signal({"column": column, "recent_median": state["recent_level"], "warning": warning,
                         "critical": critical}, label, weight=weight, near_band=0.2 * warning, unit=" ms")
