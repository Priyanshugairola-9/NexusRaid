"""Trend and drift analysis: how do values change over time?

Runs only when profiling found a real time axis (a date/time column or an
explicit sequence column). Plain row order is never treated as time.

Three ways of turning rows into time series ("modes"):
  regular  one measurement per timestamp at a steady interval (server metrics)
  grouped  several entities share timestamps (sensor-A, sensor-B ...): one series per entity
  events   irregular events (transactions, connections): counted and averaged per time bucket

For every series and column it computes:
  trend        Kendall's tau test for a steady rise/fall, plus a linear-regression slope
  drift        how far the recent level has moved from the early baseline (in robust SDs)
  spikes       single points far from their local neighbourhood
  level shifts sudden jumps to a new level that persists
  gaps         missing intervals in regularly sampled data
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

from app.services.analysis_config import AnalysisConfig
from app.services.explanation import make_finding
from app.utils.data_utils import format_number, robust_center_scale, round_or_none, to_jsonable

MIN_POINTS = 20
MAX_TREND_COLUMNS = 12
MAX_GROUPS = 8
MAX_TEST_POINTS = 5_000
CHART_POINTS = 400
SHIFT_WINDOW = 5
SPIKE_WINDOW = 11
REGULAR_FRACTION = 0.6
BUCKETS_MS = [
    ("1 minute", 60_000), ("5 minutes", 300_000), ("15 minutes", 900_000), ("30 minutes", 1_800_000),
    ("1 hour", 3_600_000), ("3 hours", 10_800_000), ("6 hours", 21_600_000), ("12 hours", 43_200_000),
    ("1 day", 86_400_000), ("1 week", 604_800_000),
]
EVENT_COUNT = "events per bucket"


@dataclass
class TrendResult:
    summary: dict
    findings: list[dict]
    column_states: dict[str, dict] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Building series
# --------------------------------------------------------------------------

def _time_numbers(values: pd.Series, kind: str) -> np.ndarray:
    """Time as float milliseconds since 1970 (datetime) or the raw sequence number."""
    if kind == "datetime":
        return ((values - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)).to_numpy(dtype=float)
    return values.to_numpy(dtype=float)


def _is_regular(times: np.ndarray) -> bool:
    intervals = np.diff(np.unique(times))
    if intervals.size < 5:
        return False
    median = np.median(intervals)
    if median <= 0:
        return False
    return np.mean(np.abs(intervals - median) <= 0.2 * median) >= REGULAR_FRACTION


def _choose_group_column(frame: pd.DataFrame, profile: dict, time_column: str) -> str | None:
    candidates = [
        column for column in profile["columns"]
        if column["kind"] == "categorical" and 2 <= column["unique"] <= 20
    ]
    candidates.sort(key=lambda column: ("group_key" not in column["roles"], column["unique"]))
    for column in candidates:
        subset = frame[[time_column, column["name"]]].dropna()
        if len(subset) and subset.duplicated().mean() < 0.05:
            return column["name"]
    return None


def _choose_bucket(span_ms: float) -> tuple[str, int]:
    for label, size in BUCKETS_MS:
        if span_ms / size <= 300:
            return label, size
    return BUCKETS_MS[-1]


def _build_series(frame, profile, features, time_column, axis_kind):
    """Return (mode, mode_reason, series list, extra info)."""
    times_all = _time_numbers(frame[time_column], axis_kind)
    valid = np.isfinite(times_all)
    duplicate_ratio = 1 - np.unique(times_all[valid]).size / max(1, valid.sum())
    group_column = None
    if duplicate_ratio > 0.1:
        group_column = _choose_group_column(frame, profile, time_column)

    if group_column:
        counts = frame.loc[valid, group_column].value_counts()
        groups = list(counts.index[:MAX_GROUPS])
        series = []
        for group in groups:
            rows = np.flatnonzero(valid & (frame[group_column] == group).to_numpy())
            rows = rows[np.argsort(times_all[rows], kind="stable")]
            series.append({"key": str(group), "rows": rows, "times": times_all[rows],
                           "values": {c: frame[c].to_numpy(dtype=float)[rows] for c in features}})
        reason = (f"{100 * duplicate_ratio:.0f}% of timestamps repeat because several '{group_column}' values "
                  "report at the same times, so each one is analysed as its own series.")
        if len(counts) > MAX_GROUPS:
            reason += f" Only the {MAX_GROUPS} largest groups are shown."
        return "grouped", reason, series, {"group_column": group_column}

    if duplicate_ratio <= 0.1 and _is_regular(times_all[valid]):
        rows = np.flatnonzero(valid)
        rows = rows[np.argsort(times_all[rows], kind="stable")]
        series = [{"key": "all", "rows": rows, "times": times_all[rows],
                   "values": {c: frame[c].to_numpy(dtype=float)[rows] for c in features}}]
        return "regular", "Measurements arrive at a steady interval, so each row is one point in time.", series, {}

    if axis_kind != "datetime":
        rows = np.flatnonzero(valid)
        rows = rows[np.argsort(times_all[rows], kind="stable")]
        series = [{"key": "all", "rows": rows, "times": times_all[rows],
                   "values": {c: frame[c].to_numpy(dtype=float)[rows] for c in features}}]
        return "regular", "Rows are ordered by the sequence column.", series, {}

    times = times_all[valid]
    start = times.min()
    label, size = _choose_bucket(times.max() - start)
    bucket = np.floor((times - start) / size).astype(int)
    data = pd.DataFrame({"bucket": bucket})
    for column in features:
        data[column] = frame[column].to_numpy(dtype=float)[valid]
    grouped = data.groupby("bucket")
    full_index = np.arange(bucket.max() + 1)
    counts = grouped.size().reindex(full_index, fill_value=0)
    means = grouped[features].mean().reindex(full_index) if features else pd.DataFrame(index=full_index)
    values = {EVENT_COUNT: counts.to_numpy(dtype=float)}
    for column in features:
        values[column] = means[column].to_numpy(dtype=float)
    series = [{"key": "all", "rows": None, "times": start + full_index * size, "values": values}]
    reason = ("Rows are irregular events (not a steady measurement interval), so they were counted and "
              f"averaged per {label} bucket. Numeric columns show the average per bucket.")
    return "events", reason, series, {"bucket": label}


# --------------------------------------------------------------------------
# Single-series statistics
# --------------------------------------------------------------------------

def _chunk_mean(array: np.ndarray, points: int) -> np.ndarray:
    if array.size <= points:
        return array
    chunks = np.array_split(array, points)
    with np.errstate(invalid="ignore"):
        return np.array([np.nanmean(chunk) if np.isfinite(chunk).any() else np.nan for chunk in chunks])


def _noise_sigma(values: np.ndarray) -> float:
    """Noise level estimated from point-to-point differences (robust to trends and shifts)."""
    diffs = np.diff(values)
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size < 3:
        return 0.0
    mad = np.median(np.abs(diffs - np.median(diffs)))
    sigma = 1.4826 * mad / np.sqrt(2)
    if sigma == 0:
        _, scale = robust_center_scale(diffs)
        sigma = scale / np.sqrt(2)
    return float(sigma)


def _spikes(times, values, sigma, threshold, min_size) -> list[dict]:
    if sigma <= 0:
        return []
    local = pd.Series(values).rolling(SPIKE_WINDOW, center=True, min_periods=3).median().to_numpy()
    with np.errstate(invalid="ignore"):
        size = np.abs(values - local)
        score = size / sigma
    hits = np.flatnonzero((np.nan_to_num(score) >= threshold) & (np.nan_to_num(size) >= min_size))
    hits = hits[np.argsort(-score[hits])][:20]
    return [
        {"index": int(i), "t": float(times[i]), "value": round_or_none(values[i]),
         "local_median": round_or_none(local[i]), "score": round_or_none(score[i], 1)}
        for i in sorted(hits)
    ]


def _level_shifts(times, values, sigma, threshold, min_size) -> list[dict]:
    """Sudden jumps to a new level that persists.

    A candidate is found by comparing the median of the 5 points before with the
    5 points after each moment. It is kept only if the jump is still clear when
    10 points on each side are compared (so short bursts count as spikes, not
    shifts) and no data gap lies inside the windows.
    """
    m = SHIFT_WINDOW
    n = values.size
    if sigma <= 0 or n < 4 * m:
        return []
    series = pd.Series(values)

    def window_score(width: int):
        before = series.rolling(width, min_periods=width).median().shift(1).to_numpy()
        after = series[::-1].rolling(width, min_periods=width).median()[::-1].to_numpy()
        # Standard error of a difference of two medians ~ 1.2533 * sigma * sqrt(2/width).
        with np.errstate(invalid="ignore"):
            return before, after, (after - before) / (1.2533 * sigma * np.sqrt(2 / width))

    before, after, score = window_score(m)
    _, _, long_score = window_score(2 * m)
    intervals = np.diff(times)
    gap_limit = 2.5 * np.median(intervals) if intervals.size else np.inf
    is_gap = np.concatenate([[False], intervals > gap_limit])

    candidates = np.flatnonzero(np.abs(np.nan_to_num(score)) >= threshold)
    chosen: list[int] = []
    for i in candidates[np.argsort(-np.abs(score[candidates]))]:
        persistent = np.sign(long_score[i]) == np.sign(score[i]) and abs(np.nan_to_num(long_score[i])) >= threshold
        crosses_gap = is_gap[max(0, i - 2 * m) : i + 2 * m].any()
        big_enough = abs(after[i] - before[i]) >= min_size
        if persistent and big_enough and not crosses_gap and all(abs(i - j) > 2 * m for j in chosen):
            chosen.append(int(i))
        if len(chosen) == 10:
            break
    return [
        {"index": i, "t": float(times[i]), "before": round_or_none(before[i]), "after": round_or_none(after[i]),
         "score": round_or_none(score[i], 1), "direction": "up" if score[i] > 0 else "down"}
        for i in sorted(chosen)
    ]


def _slope_unit(times: np.ndarray, axis_kind: str) -> tuple[str, float]:
    if axis_kind != "datetime":
        return "per step", 1.0
    span_days = (times[-1] - times[0]) / 86_400_000
    return ("per hour", 3_600_000.0) if span_days <= 7 else ("per day", 86_400_000.0)


def analyze_series(times: np.ndarray, values: np.ndarray, axis_kind: str, config: AnalysisConfig,
                   chart_points: int = CHART_POINTS) -> dict:
    keep = np.isfinite(values) & np.isfinite(times)
    times, values = times[keep], values[keep]
    n = values.size
    if n < MIN_POINTS:
        return {"skipped": True, "reason": f"Only {n} points; at least {MIN_POINTS} are needed."}
    if np.nanstd(values) == 0:
        return {"skipped": True, "reason": "The values never change."}

    test_times = _chunk_mean(times, MAX_TEST_POINTS)
    test_values = _chunk_mean(values, MAX_TEST_POINTS)
    ok = np.isfinite(test_values)
    tau, p_value = kendalltau(test_times[ok], test_values[ok])
    tau = 0.0 if not np.isfinite(tau) else float(tau)
    p_value = 1.0 if not np.isfinite(p_value) else float(p_value)

    unit_label, unit_ms = _slope_unit(times, axis_kind)
    x = (times - times[0]) / unit_ms
    slope, intercept = np.polyfit(x, values, 1)
    predicted = slope * x + intercept
    total = np.sum((values - values.mean()) ** 2)
    r_squared = 1 - np.sum((values - predicted) ** 2) / total if total > 0 else 0.0

    edge = max(3, n // 10)
    start_level = float(np.median(values[:edge]))
    end_level = float(np.median(values[-edge:]))
    pct_change = 100 * (end_level - start_level) / abs(start_level) if start_level != 0 else None
    base_center, base_scale = robust_center_scale(values[: max(5, n // 4)])
    recent_level = float(np.median(values[-max(3, int(n * 0.15)):]))
    drift_score = (recent_level - base_center) / base_scale if base_scale > 0 else None

    meaningful = abs(end_level - start_level) >= 0.5 * base_scale or (pct_change is not None and abs(pct_change) >= 5)
    if p_value < config.trend_p_value and abs(tau) >= config.trend_min_tau and meaningful:
        direction = "increasing" if tau > 0 else "decreasing"
    else:
        direction = "stable"

    sigma = _noise_sigma(values)
    # A change must also matter in practice: at least 10% of the usual range (p5-p95).
    # Without this, nearly noise-free series (e.g. disk %) turn every tiny step into a "jump".
    p5, p95 = np.percentile(values, [5, 95])
    min_size = max(0.1 * (p95 - p5), 1e-9)
    ma_window = max(3, n // 50)
    moving_average = pd.Series(values).rolling(ma_window, center=True, min_periods=1).mean().to_numpy()
    chart_t = _chunk_mean(times, chart_points)
    chart_v = _chunk_mean(values, chart_points)
    chart_ma = _chunk_mean(moving_average, chart_points)

    return {
        "skipped": False,
        "points": int(n),
        "direction": direction,
        "kendall_tau": round(tau, 3),
        "p_value": float(f"{p_value:.3g}"),
        "slope": round_or_none(slope, 6),
        "slope_unit": unit_label,
        "r_squared": round_or_none(r_squared, 3),
        "start_level": round_or_none(start_level),
        "end_level": round_or_none(end_level),
        "pct_change": round_or_none(pct_change, 2),
        "baseline_median": round_or_none(base_center),
        "baseline_spread": round_or_none(base_scale),
        "recent_level": round_or_none(recent_level),
        "drift_score": round_or_none(drift_score, 2),
        "drifted": bool(drift_score is not None and abs(drift_score) >= config.drift_threshold),
        "noise_sigma": round_or_none(sigma),
        "spikes": _spikes(times, values, sigma, config.spike_threshold, min_size),
        "level_shifts": _level_shifts(times, values, sigma, config.shift_threshold, min_size),
        "moving_average_window": ma_window,
        "chart": [
            {"t": float(t), "v": round_or_none(v), "ma": round_or_none(ma)}
            for t, v, ma in zip(chart_t, chart_v, chart_ma) if np.isfinite(t)
        ],
    }


def _gaps(times: np.ndarray, key: str) -> list[dict]:
    if not _is_regular(times):
        return []
    intervals = np.diff(times)
    median = float(np.median(intervals))
    gaps = []
    for i in np.flatnonzero(intervals > 2.5 * median):
        gaps.append({
            "series": key, "start": float(times[i]), "end": float(times[i + 1]),
            "duration_ms": float(intervals[i]), "expected_interval_ms": median,
            "missing_points": int(round(intervals[i] / median)) - 1,
        })
    return gaps


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

def _format_time(value: float, axis_kind: str) -> str:
    if axis_kind != "datetime":
        return format_number(value)
    return pd.Timestamp(value, unit="ms").strftime("%Y-%m-%d %H:%M")


def _trend_findings(results: list[dict], gaps: list[dict], axis_kind: str, mode: str) -> list[dict]:
    findings = []
    for item in results:
        stats = item["stats"]
        if stats.get("skipped"):
            continue
        column, key = item["column"], item["series"]
        where = f"{column}" + (f" ({key})" if key != "all" else "")
        if stats["direction"] != "stable" or stats["drifted"]:
            strong = stats["p_value"] < 1e-6 and abs(stats["kendall_tau"]) >= 0.5
            change = (f"{stats['pct_change']:+.1f}%" if stats["pct_change"] is not None
                      else f"{format_number(stats['start_level'])} -> {format_number(stats['end_level'])}")
            title = (f"{where} is {stats['direction']} ({change})" if stats["direction"] != "stable"
                     else f"{where} has drifted away from its early level")
            findings.append(make_finding(
                source="trend",
                category="trend",
                severity="notice",
                title=title,
                what_happened=(
                    f"The typical level of {where} moved from {format_number(stats['start_level'])} at the start to "
                    f"{format_number(stats['end_level'])} at the end of the period."
                ),
                columns=[column],
                observed=f"Recent level {format_number(stats['recent_level'])}; Kendall tau {stats['kendall_tau']} "
                         f"(p = {stats['p_value']}); slope {format_number(stats['slope'])} {stats['slope_unit']}.",
                comparison=f"Early baseline: median {format_number(stats['baseline_median'])}, robust spread "
                           f"{format_number(stats['baseline_spread'])}. Drift = {stats['drift_score']} spreads.",
                why_flagged="Kendall's tau tests for a steady rise or fall; drift compares the latest 15% of points "
                            "with the first 25%.",
                method="Kendall rank trend test, linear regression, baseline drift score",
                could_indicate="Gradual change such as growing load, resource exhaustion, sensor drift or a "
                               "changing population. It could also be a normal seasonal pattern.",
                confidence="high" if strong else "medium",
                confidence_basis=(
                    "Neighbouring time points are correlated, which makes p-values look stronger than they are; "
                    "a strict p-value and a minimum effect size are therefore required."
                ),
                needs="Whether the change was planned (a deployment, a new workload, a season) and data from "
                      "earlier periods for comparison.",
                next_steps="Look at the time-series chart for where the change starts and compare with known events.",
                evidence={"series": key, "column": column},
            ))
        shifts = stats.get("level_shifts", [])
        if shifts:
            largest = max(shifts, key=lambda shift: abs(shift["score"]))
            findings.append(make_finding(
                source="trend",
                category="change",
                severity="notice",
                title=f"{len(shifts)} sudden level change(s) in {where}",
                what_happened=f"{where} jumped from {format_number(largest['before'])} to "
                              f"{format_number(largest['after'])} around {_format_time(largest['t'], axis_kind)}.",
                columns=[column],
                observed=f"Largest jump score {largest['score']} (noise-normalised).",
                comparison="Median of the 5 points before versus the 5 points after each moment.",
                why_flagged="The new level persisted for several points, so it is not a single spike.",
                method="Rolling-median level-shift detection",
                could_indicate="A configuration change, restart, failover, recalibration or a real change in demand.",
                confidence="high" if abs(largest["score"]) >= 12 else "medium",
                confidence_basis="Jump size compared with the series' own point-to-point noise.",
                needs="A change log or event history for that time.",
                next_steps="Check what changed in the system or environment at that time.",
                evidence={"series": key, "column": column},
            ))
        spikes = stats.get("spikes", [])
        if spikes:
            findings.append(make_finding(
                source="trend",
                category="anomaly",
                severity="info",
                title=f"{len(spikes)} short spike(s) in {where}",
                what_happened=f"{len(spikes)} point(s) of {where} were far from their neighbouring points.",
                columns=[column],
                observed=", ".join(f"{format_number(spike['value'])} at {_format_time(spike['t'], axis_kind)}"
                                   for spike in spikes[:3]) + (" ..." if len(spikes) > 3 else ""),
                comparison="Each point is compared with the median of the 11 points around it"
                           + (" (each point is one time bucket)." if mode == "events" else "."),
                why_flagged="Contextual spikes can hide inside a normal overall range, which global checks miss.",
                method="Rolling-median spike detection",
                could_indicate="Brief load bursts, transient errors, or glitches in measurement.",
                confidence="medium",
                confidence_basis="Spike size relative to point-to-point noise.",
                needs="Higher-resolution data around those moments.",
                next_steps="Check whether the spikes line up across metrics (Anomaly Explorer, sorted by time).",
                evidence={"series": key, "column": column},
            ))
    if gaps:
        total_missing = sum(gap["missing_points"] for gap in gaps)
        longest = max(gaps, key=lambda gap: gap["duration_ms"])
        findings.append(make_finding(
            source="trend",
            category="data_quality",
            severity="notice",
            title=f"{len(gaps)} gap(s) in the time series (~{total_missing:,} missing points)",
            what_happened="Some expected measurements are missing.",
            columns=[],
            observed=f"Longest gap: {longest['duration_ms'] / 60000:,.0f} minutes"
                     + (f" in {longest['series']}" if longest["series"] != "all" else "")
                     + f", starting {_format_time(longest['start'], axis_kind)}.",
            comparison=f"Expected interval: {longest['expected_interval_ms'] / 60000:,.1f} minutes.",
            why_flagged="An interval more than 2.5x the usual interval is treated as a gap.",
            method="Interval analysis",
            could_indicate="Collector downtime, connectivity loss, or a device that stopped reporting.",
            confidence="high",
            confidence_basis="Directly measured from timestamps.",
            needs="Collector or device logs for the gap periods.",
            next_steps="Do not interpret trends across long gaps without checking what happened.",
        ))
    return findings


def _co_movement_finding(states: dict, mode: str) -> tuple[dict, dict | None]:
    increasing = [column for column, state in states.items() if state["direction"] == "increasing"]
    decreasing = [column for column, state in states.items() if state["direction"] == "decreasing"]
    info = {
        "increasing": increasing,
        "decreasing": decreasing,
        "note": "Signals that change over the same period may be related, but this does not show that one "
                "causes the other.",
    }
    changing = increasing + decreasing
    if len(changing) < 2:
        return info, None
    finding = make_finding(
        source="trend",
        category="pattern",
        severity="notice",
        title=f"{len(changing)} signals changed together over the same period",
        what_happened=(
            (f"Rising: {', '.join(increasing)}. " if increasing else "")
            + (f"Falling: {', '.join(decreasing)}." if decreasing else "")
        ).strip(),
        columns=changing,
        observed=f"{len(changing)} columns show statistically clear trends in the same time window.",
        comparison="Each column is tested separately against its own early baseline.",
        why_flagged="Several signals moving at once is a stronger sign of a system-wide change than one signal.",
        method="Combination of per-column trend tests",
        could_indicate="A shared cause such as rising load or a degrading component. It does not establish which "
                       "signal drives which.",
        confidence="medium",
        confidence_basis="Co-occurrence over time; no causal test is performed.",
        needs="Domain knowledge or experiments to establish cause and effect.",
        next_steps="Compare the onset times of each trend on the time-series charts.",
    )
    return info, finding


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _markers(series: dict, column: str, column_masks: dict, axis_kind: str) -> list[dict]:
    mask = column_masks.get(column)
    if mask is None or series["rows"] is None:
        return []
    flagged = np.flatnonzero(mask[series["rows"]])[:200]
    values = series["values"][column]
    return [{"t": float(series["times"][i]), "v": round_or_none(values[i])} for i in flagged]


def analyze_trends(frame: pd.DataFrame, profile: dict, features: list[str], config: AnalysisConfig,
                   column_masks: dict | None = None) -> TrendResult:
    axis = profile["time_axis"]
    if not axis.get("available"):
        return TrendResult(summary={"available": False, "reason": axis["reason"]}, findings=[])

    time_column, axis_kind = axis["column"], axis["kind"]
    columns = features[:MAX_TREND_COLUMNS]
    mode, mode_reason, series_list, extra = _build_series(frame, profile, columns, time_column, axis_kind)
    if mode == "events":
        columns = [EVENT_COUNT] + columns
    column_masks = column_masks or {}

    results, gaps = [], []
    chart_series = []
    chart_points = max(120, CHART_POINTS // max(1, len(series_list)))
    for series in series_list:
        if mode != "events":
            gaps += _gaps(series["times"], series["key"])
        for column in columns:
            stats = analyze_series(series["times"], series["values"][column], axis_kind, config, chart_points)
            results.append({"series": series["key"], "column": column, "stats": stats})
            if not stats.get("skipped"):
                chart_series.append({
                    "series": series["key"], "column": column, "points": stats.pop("chart"),
                    "markers": _markers(series, column, column_masks, axis_kind),
                })

    states: dict[str, dict] = {}
    for item in results:
        stats = item["stats"]
        if stats.get("skipped"):
            continue
        state = states.setdefault(item["column"], {
            "direction": "stable", "drift_score": 0.0, "pct_change": None, "recent_level": None,
            "series_changing": [], "spikes": 0, "level_shifts": 0,
        })
        if stats["direction"] != "stable":
            state["series_changing"].append(item["series"])
            if state["direction"] == "stable":
                state["direction"] = stats["direction"]
        drift = stats["drift_score"] or 0.0
        if abs(drift) > abs(state["drift_score"]):
            state["drift_score"] = drift
            state["pct_change"] = stats["pct_change"]
            state["recent_level"] = stats["recent_level"]
        if state["recent_level"] is None:
            state["recent_level"] = stats["recent_level"]
        state["spikes"] += len(stats["spikes"])
        state["level_shifts"] += len(stats["level_shifts"])

    co_movement, co_finding = _co_movement_finding(states, mode)
    findings = _trend_findings(results, gaps, axis_kind, mode)
    if co_finding:
        findings.append(co_finding)

    summary = {
        "available": True,
        "time_column": time_column,
        "axis_kind": axis_kind,
        "mode": mode,
        "mode_reason": mode_reason,
        **extra,
        "columns": columns,
        "series_keys": [series["key"] for series in series_list],
        "results": [
            {"series": item["series"], "column": item["column"],
             **{key: value for key, value in item["stats"].items() if key != "chart"}}
            for item in results
        ],
        "trend_summary": [
            {"series": item["series"], "column": item["column"], "direction": item["stats"]["direction"],
             "pct_change": item["stats"]["pct_change"], "drift_score": item["stats"]["drift_score"]}
            for item in results if not item["stats"].get("skipped")
        ],
        "charts": chart_series,
        "gaps": gaps[:50],
        "gap_count": len(gaps),
        "co_movement": co_movement,
        "limitations": [
            "Trends describe the past period only; they are not forecasts.",
            "Neighbouring time points are correlated, so significance tests are applied strictly.",
            "Seasonal patterns (daily cycles) can look like trends over short periods.",
        ],
    }
    if columns and len(columns) < len(features) + (1 if mode == "events" else 0):
        summary["limitations"].append(f"Only the first {MAX_TREND_COLUMNS} numeric columns are analysed over time.")
    return TrendResult(summary=to_jsonable(summary), findings=findings, column_states=states)
