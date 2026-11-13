"""Anomaly detection: which values or rows are statistically unusual?

Two levels:
  * Univariate: one column at a time ("this CPU value is far above the rest").
  * Multivariate: whole rows ("each value is normal, but this combination is rare").

Method choice is explicit and recorded (see choose_univariate_method). A flag
means "statistically unusual compared with the rest of this dataset"; it does
not mean an error, attack, fraud or failure.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors

from app.services.analysis_config import AnalysisConfig
from app.services.explanation import make_finding
from app.utils.data_utils import format_number, name_tokens, robust_center_scale, round_or_none, to_jsonable

MIN_ROWS_UNIVARIATE = 20
MIN_ROWS_MULTIVARIATE = 50
MAX_ROWS_LOF = 20_000
MAX_ROWS_DBSCAN = 10_000
MAX_STORED_RECORDS = 2_000
MAX_VALUES_PER_RECORD = 60
LABEL_HINT_TOKENS = {"anomaly", "fraud", "incident", "failure", "attack", "label", "outlier", "alert", "fault"}

METHOD_NAMES = {
    "zscore": "Z-score",
    "modified_zscore": "Modified Z-score (median/MAD)",
    "iqr": "IQR fences",
    "iqr_log": "IQR fences on log scale",
    "isolation_forest": "Isolation Forest",
    "lof": "Local Outlier Factor",
    "dbscan": "DBSCAN noise points",
}


@dataclass
class AnomalyResult:
    summary: dict
    records: list[dict]
    findings: list[dict]
    column_masks: dict[str, np.ndarray] = field(default_factory=dict)
    multivariate_mask: np.ndarray | None = None
    any_mask: np.ndarray | None = None


# --------------------------------------------------------------------------
# Univariate
# --------------------------------------------------------------------------

def choose_univariate_method(values: np.ndarray, requested: str) -> tuple[str | None, str]:
    """Pick a method for one column and say why. Returns (method, reason)."""
    n = values.size
    if n < MIN_ROWS_UNIVARIATE:
        return None, f"Only {n} values; at least {MIN_ROWS_UNIVARIATE} are needed to define 'unusual'."
    if np.unique(values).size <= 2:
        return None, "The column has only one or two distinct values."
    q1, q3 = np.percentile(values, [25, 75])
    skew = float(pd.Series(values).skew())
    positive_and_skewed = values.min() >= 0 and skew > 2

    if requested == "zscore":
        if n < 30:
            return None, "Z-score needs at least 30 values to estimate mean and spread."
        return "zscore", "Z-score was requested. It assumes a roughly bell-shaped distribution."
    if requested == "modified_zscore":
        return "modified_zscore", "Modified Z-score was requested (median/MAD, robust to outliers)."
    if requested == "iqr":
        if q3 == q1:
            return None, "More than half of the values are identical, so the IQR is zero."
        if positive_and_skewed:
            return "iqr_log", "IQR was requested; the column is strongly right-skewed, so fences use a log scale."
        return "iqr", "IQR was requested."

    # Automatic choice.
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if abs(skew) <= 1 and mad > 0:
        return "modified_zscore", (
            f"The distribution is roughly symmetric (skewness {skew:.2f}), so the modified Z-score is used. "
            "It is based on the median and MAD, so the outliers themselves do not distort it."
        )
    if q3 == q1:
        return None, "More than half of the values are identical, so spread-based methods cannot define 'unusual'."
    if positive_and_skewed:
        return "iqr_log", (
            f"The distribution is strongly right-skewed (skewness {skew:.2f}), typical for amounts, sizes and "
            "durations. IQR fences are applied on a log scale so that ordinary large values are not all flagged."
        )
    return "iqr", f"The distribution is skewed (skewness {skew:.2f}), so IQR fences are used instead of Z-scores."


def _univariate_scores(values: np.ndarray, method: str, config: AnalysisConfig):
    """Score one column. Returns (deviation, flagged_mask, threshold_or_None, fences).

    Deviation is expressed in (robust) standard-deviation units for every method,
    so rows flagged by different methods can be ranked together.
    """
    finite = values[np.isfinite(values)]
    valid = np.isfinite(values)
    if method == "zscore":
        mean, std = finite.mean(), finite.std()
        deviation = np.abs(values - mean) / std
        threshold = config.zscore_threshold
        fences = (mean - threshold * std, mean + threshold * std)
    elif method == "modified_zscore":
        median = np.median(finite)
        mad = np.median(np.abs(finite - median))
        deviation = 0.6745 * np.abs(values - median) / mad
        threshold = config.modified_zscore_threshold
        half_width = threshold * mad / 0.6745
        fences = (median - half_width, median + half_width)
    else:
        use_log = method == "iqr_log"
        transform = np.log1p if use_log else (lambda x: x)
        scale_values = transform(finite)
        q1, median, q3 = np.percentile(scale_values, [25, 50, 75])
        iqr = q3 - q1
        low, high = q1 - config.iqr_multiplier * iqr, q3 + config.iqr_multiplier * iqr
        with np.errstate(invalid="ignore"):
            deviation = np.abs(transform(values) - median) / (iqr / 1.349)
        fences = (np.expm1(low), np.expm1(high)) if use_log else (low, high)
        with np.errstate(invalid="ignore"):
            mask = valid & ((values < fences[0]) | (values > fences[1]))
        return deviation, mask, None, {"low": fences[0], "high": fences[1]}

    with np.errstate(invalid="ignore"):
        mask = valid & (deviation > threshold)
    return deviation, mask, threshold, {"low": fences[0], "high": fences[1]}


def _detect_univariate(frame: pd.DataFrame, features: list[str], config: AnalysisConfig):
    columns_info = []
    masks: dict[str, np.ndarray] = {}
    scores_by_column: dict[str, np.ndarray] = {}
    for column in features:
        values = frame[column].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        method, reason = choose_univariate_method(finite, config.univariate_method)
        info = {"column": column, "method": method, "method_name": METHOD_NAMES.get(method), "reason": reason}
        if method is None:
            info["skipped"] = True
            columns_info.append(info)
            continue
        scores, mask, threshold, fences = _univariate_scores(values, method, config)
        p5, median, p95 = np.percentile(finite, [5, 50, 95])
        info.update({
            "skipped": False,
            "threshold": threshold,
            "threshold_explanation": (
                f"Flagged when the deviation exceeds {threshold}." if threshold is not None
                else f"Flagged when outside Q1 - {config.iqr_multiplier} x IQR or Q3 + {config.iqr_multiplier} x IQR."
            ),
            "flag_bounds": {"low": round_or_none(fences["low"]), "high": round_or_none(fences["high"])},
            "normal_range": {"p5": round_or_none(p5), "median": round_or_none(median), "p95": round_or_none(p95)},
            "flagged": int(mask.sum()),
            "flagged_high": int((mask & (values > median)).sum()),
            "flagged_low": int((mask & (values < median)).sum()),
            "flagged_pct": round(100 * mask.sum() / max(1, finite.size), 3),
            "max_deviation": round_or_none(np.nanmax(np.where(mask, scores, np.nan)) if mask.any() else None, 2),
        })
        masks[column] = mask
        scores_by_column[column] = np.where(mask, scores, 0.0)
        columns_info.append(info)
    return columns_info, masks, scores_by_column


# --------------------------------------------------------------------------
# Multivariate
# --------------------------------------------------------------------------

def _prepare_matrix(frame: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Impute, log-transform skewed columns and robust-scale. Returns (X, usable_rows, steps)."""
    data = frame[features].astype(float)
    usable = (data.notna().mean(axis=1) >= 0.5).to_numpy()
    steps = []
    excluded = int((~usable).sum())
    if excluded:
        steps.append(f"{excluded:,} row(s) with more than half of the features missing were not scored.")
    data = data[usable]
    missing = int(data.isna().sum().sum())
    if missing:
        steps.append(f"{missing:,} missing value(s) were filled with the column median for this step only.")
    data = data.fillna(data.median())

    logged = []
    for column in features:
        series = data[column]
        if series.min() >= 0 and series.skew() > 1:
            data[column] = np.log1p(series)
            logged.append(column)
    if logged:
        steps.append(f"Strongly right-skewed columns were log-transformed: {', '.join(logged)}.")

    medians = data.median()
    spread = (data.quantile(0.75) - data.quantile(0.25)).replace(0, np.nan)
    spread = spread.fillna(data.std().replace(0, 1.0))
    scaled = (data - medians) / spread
    steps.append("Each column was centred on its median and divided by its IQR (robust scaling).")
    return scaled.to_numpy(), usable, steps


def _robust_upper_z(scores: np.ndarray) -> np.ndarray:
    """How far above the typical score each row is, in robust-SD units."""
    center, scale = robust_center_scale(scores)
    if scale == 0:
        return np.zeros_like(scores)
    return (scores - center) / scale


def _detect_multivariate(frame: pd.DataFrame, features: list[str], config: AnalysisConfig) -> dict:
    n = len(frame)
    info: dict = {"features": features}
    if len(features) < 2:
        info.update(skipped=True, reason="At least two usable numeric columns are needed for row-level detection.")
        return info
    if config.multivariate_method == "none":
        info.update(skipped=True, reason="Row-level detection was turned off in the analysis settings.")
        return info
    if n < MIN_ROWS_MULTIVARIATE:
        info.update(skipped=True, reason=f"Only {n} rows; at least {MIN_ROWS_MULTIVARIATE} are needed.")
        return info

    method = config.multivariate_method
    reason = ""
    if method == "lof" and n > MAX_ROWS_LOF:
        reason = f"LOF was requested but is too slow above {MAX_ROWS_LOF:,} rows on modest hardware; "
        method = "isolation_forest"
    if method == "dbscan" and n > MAX_ROWS_DBSCAN:
        reason = f"DBSCAN was requested but is too slow above {MAX_ROWS_DBSCAN:,} rows; "
        method = "isolation_forest"
    if method == "auto":
        method = "isolation_forest"

    matrix, usable, steps = _prepare_matrix(frame, features)
    seed = config.random_seed
    if method == "isolation_forest":
        model = IsolationForest(n_estimators=100, random_state=seed)
        model.fit(matrix)
        raw_scores = -model.score_samples(matrix)
        reason += (
            "Isolation Forest isolates each row with random splits; rows that are isolated in few splits are "
            "unusual. It handles many columns, needs no distribution assumption and scales to large files."
        )
        params = {"n_estimators": 100, "random_state": seed}
    elif method == "lof":
        neighbors = min(config.lof_neighbors, len(matrix) - 1)
        model = LocalOutlierFactor(n_neighbors=neighbors)
        model.fit(matrix)
        raw_scores = -model.negative_outlier_factor_
        reason += (
            "Local Outlier Factor compares each row's local density with that of its neighbours, so it can find "
            "rows that are unusual within their own cluster."
        )
        params = {"n_neighbors": neighbors}
    else:
        k = min(config.dbscan_min_samples, len(matrix) - 1)
        distances, _ = NearestNeighbors(n_neighbors=k).fit(matrix).kneighbors(matrix)
        kth = distances[:, -1]
        eps = float(np.percentile(kth, 95))
        labels = DBSCAN(eps=max(eps, 1e-9), min_samples=k).fit_predict(matrix)
        raw_scores = kth
        reason += (
            "DBSCAN groups dense regions into clusters; rows that belong to no cluster ('noise') are unusual. "
            f"eps was set to the 95th percentile of each row's distance to its {k}th neighbour."
        )
        params = {"min_samples": k, "eps": round(eps, 4)}

    deviation = _robust_upper_z(raw_scores)
    if method == "dbscan":
        flagged_usable = labels == -1
    else:
        flagged_usable = deviation > config.multivariate_threshold

    mask = np.zeros(n, dtype=bool)
    mask[usable] = flagged_usable
    full_deviation = np.zeros(n)
    full_deviation[usable] = deviation
    full_matrix = np.full((n, len(features)), np.nan)
    full_matrix[usable] = matrix
    info.update({
        "skipped": False,
        "method": method,
        "method_name": METHOD_NAMES[method],
        "reason": reason,
        "preprocessing": steps,
        "parameters": params,
        "threshold": config.multivariate_threshold if method != "dbscan" else None,
        "threshold_explanation": (
            f"A row is flagged when its anomaly score is more than {config.multivariate_threshold} robust "
            "standard deviations above the typical row's score. A fixed 'contamination' percentage is not "
            "used, because that would force a quota of anomalies even into clean data."
            if method != "dbscan" else "A row is flagged when DBSCAN assigns it to no cluster."
        ),
        "scored_rows": int(usable.sum()),
        "flagged": int(mask.sum()),
        "flagged_pct": round(100 * mask.sum() / max(1, usable.sum()), 3),
        "_mask": mask,
        "_deviation": full_deviation,
        "_matrix": full_matrix,
    })
    return info


# --------------------------------------------------------------------------
# Validation against labels (only when the data has a usable label column)
# --------------------------------------------------------------------------

def _find_label_column(profile: dict) -> str | None:
    for column in profile["columns"]:
        if column["kind"] == "boolean" and "label_candidate" in column["roles"]:
            if LABEL_HINT_TOKENS & set(name_tokens(column["name"])):
                return column["name"]
    return None


def _confusion(predicted: np.ndarray, actual: np.ndarray) -> dict:
    tp = int((predicted & actual).sum())
    fp = int((predicted & ~actual).sum())
    fn = int((~predicted & actual).sum())
    tn = int((~predicted & ~actual).sum())

    def ratio(a: int, b: int):
        return round(a / b, 4) if b else None

    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else 0.0
    return {
        "true_positives": tp, "false_positives": fp, "false_negatives": fn, "true_negatives": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": ratio(fp, fp + tn), "false_negative_rate": ratio(fn, fn + tp),
    }


def _label_validation(frame: pd.DataFrame, profile: dict, any_mask: np.ndarray, multi_mask) -> dict:
    label = _find_label_column(profile)
    if label is None:
        return {"available": False, "reason": "No labelled outcome column (e.g. 'is_anomaly', 'incident') found."}
    labels = frame[label]
    known = labels.notna().to_numpy()
    actual = labels.fillna(False).astype(bool).to_numpy()
    positive_rate = actual[known].mean()
    if not 0.001 <= positive_rate <= 0.3:
        return {"available": False, "label_column": label,
                "reason": f"Label '{label}' marks {100 * positive_rate:.1f}% of rows as positive; too few or too "
                          "many for a meaningful comparison."}
    result = {
        "available": True,
        "label_column": label,
        "positives": int(actual[known].sum()),
        "rows_compared": int(known.sum()),
        "any_method": _confusion(any_mask[known], actual[known]),
        "note": "The detectors never saw this label; it is only used afterwards to measure agreement. "
                "Results are in-sample and, on synthetic data, optimistic. A false positive here can still be a "
                "real data issue that the label does not cover.",
    }
    if multi_mask is not None:
        result["multivariate"] = _confusion(multi_mask[known], actual[known])
    return result


# --------------------------------------------------------------------------
# Records and findings
# --------------------------------------------------------------------------

def _build_records(frame, features, univariate_info, column_masks, column_scores, multi, time_column) -> tuple[list, int]:
    n = len(frame)
    any_mask = np.zeros(n, dtype=bool)
    for mask in column_masks.values():
        any_mask |= mask
    multi_mask = multi.get("_mask")
    if multi_mask is not None:
        any_mask |= multi_mask
    positions = np.flatnonzero(any_mask)

    ranges = {info["column"]: info for info in univariate_info if not info.get("skipped")}
    deviation = np.zeros(n)
    for scores in column_scores.values():
        deviation = np.maximum(deviation, scores)
    if multi_mask is not None:
        deviation = np.maximum(deviation, np.where(multi_mask, multi["_deviation"], 0))

    order = positions[np.argsort(-deviation[positions], kind="stable")][:MAX_STORED_RECORDS]
    value_columns = list(frame.columns[:MAX_VALUES_PER_RECORD])
    records = []
    for position in order:
        methods, columns, reasons = [], [], []
        for column, mask in column_masks.items():
            if mask[position]:
                info = ranges[column]
                value = frame[column].iat[position]
                normal = info["normal_range"]
                side = "above" if value > normal["median"] else "below"
                methods.append(info["method"])
                columns.append(column)
                reasons.append(
                    f"{column} = {format_number(value)} is far {side} its usual range "
                    f"({format_number(normal['p5'])} to {format_number(normal['p95'])} holds 90% of values; "
                    f"median {format_number(normal['median'])}). Detected by {info['method_name']}."
                )
        if multi_mask is not None and multi_mask[position]:
            methods.append(multi["method"])
            row = multi["_matrix"][position]
            robust_z = np.abs(row) * 1.349
            top = np.argsort(-robust_z)[:3]
            if robust_z[top[0]] < 3:
                reasons.append(
                    f"{multi['method_name']}: no single value is extreme, but the combination of "
                    f"{', '.join(features[i] for i in top)} is rare compared with other rows."
                )
            else:
                parts = [
                    f"{features[i]} ({'high' if row[i] > 0 else 'low'})" for i in top if robust_z[i] >= 2
                ]
                reasons.append(f"{multi['method_name']}: the row stands out mainly through {', '.join(parts)}.")
            for i in top:
                if robust_z[i] >= 2 and features[i] not in columns:
                    columns.append(features[i])
        record = {
            "row_index": int(position),
            "row_number": int(position) + 1,
            "methods": sorted(set(methods)),
            "deviation": round(float(deviation[position]), 2),
            "columns": columns,
            "reasons": reasons,
            "values": to_jsonable({column: frame[column].iat[position] for column in value_columns}),
        }
        if time_column:
            record["time"] = to_jsonable(frame[time_column].iat[position])
        records.append(record)
    return records, any_mask


def _confidence_for_column(info: dict, observations: int) -> tuple[str, str]:
    deviation = info.get("max_deviation") or 0
    threshold = info.get("threshold") or 3.5
    if observations < 100:
        return "low", f"Only {observations} observations, so the 'normal' range itself is uncertain."
    if info["flagged_pct"] > 5:
        return "low", (f"{info['flagged_pct']:.1f}% of values are flagged; that many usually means a heavy-tailed "
                       "distribution or a change of regime rather than isolated anomalies.")
    if deviation >= 2 * threshold:
        return "high", f"The most extreme value is {deviation:.1f} robust SDs from the median (threshold {threshold})."
    return "medium", "Flagged values are beyond the threshold but not by a wide margin."


def _findings(univariate_info, multi, label_check, observations) -> list[dict]:
    findings = []
    for info in univariate_info:
        if info.get("skipped") or not info["flagged"]:
            continue
        column = info["column"]
        normal = info["normal_range"]
        direction = (
            "high" if info["flagged_high"] and not info["flagged_low"]
            else "low" if info["flagged_low"] and not info["flagged_high"] else "high and low"
        )
        confidence, basis = _confidence_for_column(info, observations)
        findings.append(make_finding(
            source="universal",
            category="anomaly",
            severity="notice" if confidence != "low" else "info",
            title=f"{info['flagged']:,} unusually {direction} value(s) in {column}",
            what_happened=f"{info['flagged']:,} value(s) of {column} ({info['flagged_pct']:.2f}%) lie outside the "
                          "range expected from the rest of the column.",
            columns=[column],
            observed=f"Most extreme deviation: {info['max_deviation']} robust SDs from the median.",
            comparison=f"90% of values lie between {format_number(normal['p5'])} and {format_number(normal['p95'])} "
                       f"(median {format_number(normal['median'])}). Flag bounds: below "
                       f"{format_number(info['flag_bounds']['low'])} or above {format_number(info['flag_bounds']['high'])}.",
            why_flagged=info["reason"],
            method=info["method_name"],
            could_indicate="A genuine unusual event, a measurement or data-entry error, or a rare but normal value.",
            confidence=confidence,
            confidence_basis=basis,
            needs="Context for these rows: what happened at that time or to that entity, and whether the value "
                  "is physically possible.",
            next_steps="Open the Anomaly Explorer filtered to this column and check the flagged rows' other values.",
            evidence={"column": column, "flagged": info["flagged"]},
        ))

    if not multi.get("skipped") and multi.get("flagged"):
        flagged_pct = multi["flagged_pct"]
        confidence = "low" if flagged_pct > 5 or observations < 100 else "medium"
        findings.append(make_finding(
            source="universal",
            category="anomaly",
            severity="notice",
            title=f"{multi['flagged']:,} row(s) with unusual combinations of values",
            what_happened=f"{multi['method_name']} flagged {multi['flagged']:,} of {multi['scored_rows']:,} rows "
                          f"({flagged_pct:.2f}%) as unlike the rest when all features are considered together.",
            columns=multi["features"],
            observed=f"{multi['flagged']:,} row(s) above the score threshold.",
            comparison=multi["threshold_explanation"],
            why_flagged=multi["reason"],
            method=multi["method_name"],
            could_indicate="Rows where several metrics behave unusually at the same time, or an unusual mix of "
                           "otherwise normal values.",
            confidence=confidence,
            confidence_basis="Row-level scores are relative to this dataset; they are not calibrated probabilities.",
            needs="Knowledge of which combinations are normal for this system or population.",
            next_steps="In the Anomaly Explorer, sort by deviation and read each row's explanation.",
        ))

    if label_check.get("available"):
        metrics = label_check["any_method"]
        findings.append(make_finding(
            source="universal",
            category="validation",
            severity="info",
            title=f"Agreement with the '{label_check['label_column']}' label",
            what_happened="The dataset contains a label column, so detections were compared with it afterwards.",
            columns=[label_check["label_column"]],
            observed=f"Precision {metrics['precision']}, recall {metrics['recall']}, F1 {metrics['f1']}.",
            comparison=f"{label_check['positives']} labelled positives among {label_check['rows_compared']:,} rows.",
            why_flagged="Measuring agreement with known labels shows how useful the unsupervised flags are here.",
            method="Confusion matrix of flags versus labels",
            could_indicate="How many flags match labelled events (precision) and how many labelled events were "
                           "found (recall).",
            confidence="medium",
            confidence_basis="In-sample comparison on one dataset; no train/test split is involved.",
            needs="Labels from a different time period to test whether the detector generalises.",
            next_steps="Inspect false negatives (labelled but not flagged) to see what the detectors miss.",
        ))
    return findings


def detect_anomalies(frame: pd.DataFrame, profile: dict, features: list[str], config: AnalysisConfig,
                     time_column: str | None = None) -> AnomalyResult:
    observations = len(frame)
    univariate_info, column_masks, column_scores = _detect_univariate(frame, features, config)
    multi = _detect_multivariate(frame, features, config)
    records, any_mask = _build_records(frame, features, univariate_info, column_masks, column_scores, multi,
                                       time_column)
    multi_mask = multi.get("_mask")
    label_check = _label_validation(frame, profile, any_mask, multi_mask)
    findings = _findings(univariate_info, multi, label_check, observations)

    flagged_rows = int(any_mask.sum())
    public_multi = {key: value for key, value in multi.items() if not key.startswith("_")}
    summary = {
        "observations": observations,
        "features": features,
        "univariate": univariate_info,
        "multivariate": public_multi,
        "flagged_rows": flagged_rows,
        "flagged_pct": round(100 * flagged_rows / max(1, observations), 3),
        "column_flag_counts": {column: int(mask.sum()) for column, mask in column_masks.items() if mask.any()},
        "stored_records": len(records),
        "records_capped": flagged_rows > len(records),
        "label_validation": label_check,
        "note": "Flags mark statistically unusual values relative to this dataset. They are leads to "
                "investigate, not confirmed incidents.",
    }
    return AnomalyResult(
        summary=to_jsonable(summary),
        records=records,
        findings=findings,
        column_masks=column_masks,
        multivariate_mask=multi_mask,
        any_mask=any_mask,
    )
