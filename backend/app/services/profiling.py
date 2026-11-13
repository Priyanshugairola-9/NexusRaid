"""Dataset profiling: what is in each column, and how trustworthy is it?

prepare_and_profile() does two things:
1. Prepares a typed copy of the data (text that is really numbers or dates is
   converted). Every conversion is written to a cleaning log; the uploaded
   file itself is never modified and no rows are removed.
2. Describes the dataset: column kinds, statistics, quality indicators,
   correlations and whether a usable time axis exists.

Column kinds
  numeric      measured quantities (CPU %, amount, score)
  boolean      two-valued columns (0/1, yes/no)
  datetime     dates and times
  categorical  a limited set of labels (device_id, protocol, subject)
  identifier   (almost) unique per row: transaction_id, student_id
  text         free text
  constant     a single repeated value: carries no information
  empty        no values at all
"""

import re
import warnings

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.utils.data_utils import name_tokens, round_or_none, to_jsonable

ID_TOKENS = {"id", "uuid", "guid", "key", "serial", "idx"}
CODE_TOKENS = {"port", "code", "zip", "pincode", "postal", "phone", "mobile"}
COUNT_TOKENS = {"count", "counts", "errors", "error", "num", "number", "total", "qty", "quantity"}
TIME_TOKENS = {"time", "timestamp", "date", "datetime", "ts", "epoch", "created", "at"}
SEQUENCE_TOKENS = {"seq", "sequence", "step", "tick", "sample", "reading", "cycle", "iteration"}
LABEL_TOKENS = {
    "label", "target", "class", "outcome", "result", "fraud", "anomaly", "incident",
    "failure", "failed", "churn", "attack", "is_anomaly",
}
BOOLEAN_WORDS = {"true", "false", "yes", "no", "y", "n", "t", "f"}

_PERCENT_OR_SPACES = re.compile(r"[%\s]")
# Text must look like a date or time before date parsing is attempted. Without
# this, pandas' flexible parser reads IDs such as "T0" as times of day.
_DATE_LIKE = re.compile(
    r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}:\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d|\d\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
    re.IGNORECASE,
)
_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")

MAX_TOP_VALUES = 10
HISTOGRAM_BINS = 20
MAX_CORRELATION_COLUMNS = 15
STRONG_CORRELATION = 0.7


# --------------------------------------------------------------------------
# Type conversion
# --------------------------------------------------------------------------

def _try_numeric(series: pd.Series) -> tuple[pd.Series | None, dict | None]:
    """Convert text such as '45%', ' 12 ' or '1,234' to numbers if >=95% succeed."""
    text = series.dropna().astype(str).str.strip()
    text = text[text != ""]
    if text.empty:
        return None, None
    had_percent = text.str.contains("%", regex=False).any()
    cleaned = text.str.replace(_PERCENT_OR_SPACES, "", regex=True)
    thousands_mask = cleaned.str.match(_THOUSANDS)
    cleaned = cleaned.where(~thousands_mask, cleaned.str.replace(",", "", regex=False))
    numbers = pd.to_numeric(cleaned, errors="coerce")
    success = numbers.notna().mean()
    if success < 0.95:
        return None, None

    full = pd.Series(np.nan, index=series.index, dtype=float)
    full.loc[numbers.index] = numbers.astype(float)
    failed = text[numbers.isna()]
    removed = []
    if had_percent:
        removed.append("% signs")
    if thousands_mask.any():
        removed.append("thousands separators")
    action = "Converted text to numbers"
    if removed:
        action += f" (removed {' and '.join(removed)})"
    note = {
        "action": action,
        "affected_values": int(len(text) - len(failed)),
        "failed_values": int(len(failed)),
        "failed_examples": failed.head(5).tolist(),
        "effect": "Values that could not be read as numbers are treated as missing." if len(failed) else "",
    }
    return full, note


def _try_boolean(series: pd.Series) -> pd.Series | None:
    text = series.dropna().astype(str).str.strip().str.lower()
    if text.empty or not set(text.unique()) <= BOOLEAN_WORDS or text.nunique() > 2:
        return None
    mapping = {"true": True, "yes": True, "y": True, "t": True, "false": False, "no": False, "n": False, "f": False}
    return series.map(lambda value: mapping.get(str(value).strip().lower()) if pd.notna(value) else None)


def _parse_datetimes(values: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(values, errors="coerce")
        if parsed.notna().mean() < 0.9:
            parsed = pd.to_datetime(values, errors="coerce", format="mixed")
    # Timezone-aware values are converted to UTC and stored without zone so
    # that every timestamp column can be compared with every other.
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    return parsed


def _try_datetime(series: pd.Series) -> tuple[pd.Series | None, int]:
    text = series.dropna().astype(str).str.strip()
    text = text[text != ""]
    if text.empty:
        return None, 0
    # Pure numbers ("12", "2023") are not treated as dates here.
    if pd.to_numeric(text.head(200), errors="coerce").notna().mean() > 0.5:
        return None, 0
    sample = text.sample(min(200, len(text)), random_state=0)
    if sample.str.contains(_DATE_LIKE).mean() < 0.9:
        return None, 0
    if _parse_datetimes(sample).notna().mean() < 0.9:
        return None, 0
    parsed = _parse_datetimes(series.where(series.notna(), None).astype("object"))
    failed = int(text.size - parsed.notna().sum())
    if parsed.notna().sum() < 0.9 * text.size:
        return None, 0
    return parsed, failed


def _epoch_to_datetime(series: pd.Series, tokens: list[str]) -> tuple[pd.Series | None, str | None]:
    """Numeric Unix timestamps in a column named like a time column."""
    if not TIME_TOKENS.intersection(tokens):
        return None, None
    values = series.dropna()
    if values.empty or not np.all(np.mod(values, 1) == 0):
        return None, None
    low, high = values.min(), values.max()
    if 1e9 <= low and high <= 4e9:
        return pd.to_datetime(series, unit="s", errors="coerce"), "seconds"
    if 1e12 <= low and high <= 4e12:
        return pd.to_datetime(series, unit="ms", errors="coerce"), "milliseconds"
    return None, None


# --------------------------------------------------------------------------
# Column classification
# --------------------------------------------------------------------------

def _classify(name: str, series: pd.Series, row_count: int, log: list) -> tuple[pd.Series, str, list[str], list[str]]:
    """Return (typed_series, kind, roles, notes) for one column."""
    tokens = name_tokens(name)
    token_set = set(tokens)
    roles: list[str] = []
    notes: list[str] = []
    non_null = series.dropna()

    if non_null.empty:
        return series, "empty", roles, ["Column has no values."]

    typed = series
    if ptypes.is_bool_dtype(series):
        typed = series.astype("boolean")
    elif ptypes.is_datetime64_any_dtype(series):
        typed = series
    elif not ptypes.is_numeric_dtype(series):
        converted, note = _try_numeric(series)
        if converted is not None:
            typed = converted
            log.append({"column": name, **note})
        else:
            as_bool = _try_boolean(series)
            if as_bool is not None:
                typed = as_bool.astype("boolean")
            else:
                parsed, failed = _try_datetime(series)
                if parsed is not None:
                    typed = parsed
                    log.append({
                        "column": name, "action": "Parsed text as dates/times",
                        "affected_values": int(parsed.notna().sum()), "failed_values": failed,
                        "failed_examples": [],
                        "effect": "Unparseable dates are treated as missing." if failed else "",
                    })

    if ptypes.is_numeric_dtype(typed) and not ptypes.is_bool_dtype(typed):
        typed = pd.to_numeric(typed, errors="coerce").astype(float)
        infinite = int(np.isinf(typed).sum())
        if infinite:
            typed = typed.replace([np.inf, -np.inf], np.nan)
            log.append({
                "column": name, "action": "Treated infinite values as missing",
                "affected_values": infinite, "failed_values": 0, "failed_examples": [],
                "effect": "Infinity cannot be used in statistics; check how these values were produced.",
            })
        epoch, unit = _epoch_to_datetime(typed, tokens)
        if epoch is not None:
            log.append({
                "column": name, "action": f"Interpreted numbers as Unix timestamps ({unit})",
                "affected_values": int(epoch.notna().sum()), "failed_values": 0,
                "failed_examples": [], "effect": "",
            })
            typed = epoch

    unique = typed.nunique(dropna=True)
    unique_ratio = unique / max(1, typed.notna().sum())

    if ptypes.is_datetime64_any_dtype(typed):
        kind = "datetime"
    elif ptypes.is_bool_dtype(typed):
        kind = "boolean"
    elif ptypes.is_numeric_dtype(typed):
        values = typed.dropna()
        is_integer = bool(np.all(np.mod(values, 1) == 0))
        if set(values.unique()) <= {0.0, 1.0} and unique == 2 and not COUNT_TOKENS & token_set:
            kind = "boolean"
            typed = typed.map({0.0: False, 1.0: True}).astype("boolean")
        elif token_set & CODE_TOKENS:
            kind = "categorical"
            notes.append("Numeric codes (ports, codes, phone numbers) are labels, not quantities.")
        elif token_set & ID_TOKENS and unique_ratio >= 0.9:
            kind = "identifier"
        elif is_integer and unique == len(values) and len(values) >= 10 and np.all(np.diff(values.to_numpy()) == 1):
            kind = "identifier"
            notes.append("Values count up by exactly 1, like a row number.")
        else:
            kind = "numeric"
    else:
        lengths = non_null.astype(str).str.len()
        if token_set & ID_TOKENS:
            kind = "identifier" if unique_ratio >= 0.9 else "categorical"
            if kind == "categorical":
                roles.append("group_key")
        elif unique_ratio >= 0.95 and len(non_null) >= 20:
            kind = "text" if lengths.mean() >= 40 else "identifier"
        elif lengths.mean() >= 40 and unique_ratio > 0.5:
            kind = "text"
        else:
            kind = "categorical"

    if unique == 1 and kind not in ("empty",):
        notes.append("Only one distinct value, so it carries no information for analysis.")
        kind = "constant"

    if kind in ("boolean", "categorical") and unique <= 10 and (
        token_set & LABEL_TOKENS or (len(tokens) > 1 and tokens[0] == "is")
    ):
        roles.append("label_candidate")
        notes.append("Looks like an outcome/label column; it is not used as an input feature.")
    if kind == "identifier":
        notes.append("Identifiers are excluded from numerical analysis.")
    return typed, kind, roles, notes


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def _numeric_stats(values: pd.Series) -> dict:
    finite = values[np.isfinite(values)]
    if finite.empty:
        return {}
    q1, median, q3 = finite.quantile([0.25, 0.5, 0.75])
    counts, edges = np.histogram(finite, bins=min(HISTOGRAM_BINS, max(1, finite.nunique())))
    return {
        "mean": round_or_none(finite.mean()),
        "std": round_or_none(finite.std()) if len(finite) > 1 else None,
        "min": round_or_none(finite.min()),
        "q1": round_or_none(q1),
        "median": round_or_none(median),
        "q3": round_or_none(q3),
        "max": round_or_none(finite.max()),
        "skewness": round_or_none(finite.skew()) if len(finite) > 2 else None,
        "zeros": int((finite == 0).sum()),
        "negatives": int((finite < 0).sum()),
        "histogram": {"edges": [round_or_none(edge) for edge in edges], "counts": counts.tolist()},
    }


def _top_values(series: pd.Series) -> dict:
    counts = series.astype(str).where(series.notna()).value_counts(dropna=True)
    total = int(counts.sum())
    top = counts.head(MAX_TOP_VALUES)
    return {
        "top_values": [
            {"value": str(value), "count": int(count), "pct": round(100 * count / total, 2)}
            for value, count in top.items()
        ],
        "other_count": int(total - top.sum()),
    }


def _datetime_stats(series: pd.Series) -> dict:
    values = series.dropna()
    if values.empty:
        return {}
    diffs = values.sort_values().diff().dropna().dt.total_seconds()
    return {
        "min": values.min().isoformat(),
        "max": values.max().isoformat(),
        "is_sorted": bool(values.is_monotonic_increasing),
        "duplicate_timestamps": int(values.duplicated().sum()),
        "median_interval_seconds": round_or_none(diffs.median()) if not diffs.empty else None,
    }


def _describe_column(name: str, original: pd.Series, typed: pd.Series, kind: str, roles, notes) -> dict:
    count = int(typed.notna().sum())
    total = len(typed)
    column = {
        "name": name,
        "kind": kind,
        "original_dtype": str(original.dtype),
        "count": count,
        "missing": total - count,
        "missing_pct": round(100 * (total - count) / total, 2) if total else 0.0,
        "unique": int(typed.nunique(dropna=True)),
        "roles": roles,
        "notes": notes,
    }
    if kind == "numeric":
        column.update(_numeric_stats(typed.astype(float)))
    elif kind in ("categorical", "boolean", "constant"):
        column.update(_top_values(typed))
    elif kind == "datetime":
        column.update(_datetime_stats(typed))
    elif kind in ("identifier", "text"):
        sample = typed.dropna().astype(str)
        column["examples"] = sample.head(3).tolist()
        column["avg_length"] = round_or_none(sample.str.len().mean(), 1)
    return column


# --------------------------------------------------------------------------
# Dataset-level parts
# --------------------------------------------------------------------------

def numeric_feature_columns(columns: list[dict]) -> list[str]:
    """Numeric columns that are safe to use as analysis inputs."""
    return [
        column["name"] for column in columns
        if column["kind"] == "numeric" and column["missing_pct"] < 50 and "label_candidate" not in column["roles"]
    ]


def _correlations(frame: pd.DataFrame, columns: list[dict]) -> dict:
    candidates = sorted(
        (column for column in columns if column["name"] in numeric_feature_columns(columns)),
        key=lambda column: column["missing"],
    )[:MAX_CORRELATION_COLUMNS]
    names = [column["name"] for column in candidates]
    if len(names) < 2:
        return {"available": False, "reason": "At least two numeric columns are needed.", "method": "spearman"}
    matrix = frame[names].corr(method="spearman", min_periods=10)
    pairs = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            value = matrix.loc[first, second]
            if pd.notna(value) and abs(value) >= STRONG_CORRELATION:
                pairs.append({"a": first, "b": second, "rho": round(float(value), 3)})
    pairs.sort(key=lambda pair: -abs(pair["rho"]))
    return {
        "available": True,
        "method": "spearman",
        "method_reason": "Spearman rank correlation measures any steady increasing/decreasing "
                         "relationship and does not assume normally distributed data.",
        "columns": names,
        "matrix": [[round_or_none(matrix.loc[a, b], 3) for b in names] for a in names],
        "strong_pairs": pairs[:20],
        "note": "Correlation shows that two columns move together. It does not show that one causes the other.",
    }


def select_time_axis(frame: pd.DataFrame, columns: list[dict]) -> dict:
    """Pick the column that defines time order, or explain why there is none.

    Plain row order is never assumed to be time.
    """
    datetime_columns = [
        column for column in columns if column["kind"] == "datetime" and column["missing_pct"] <= 10
    ]
    if datetime_columns:
        def preference(column: dict) -> tuple:
            named_like_time = bool(TIME_TOKENS & set(name_tokens(column["name"])))
            return (named_like_time, column["unique"])

        chosen = max(datetime_columns, key=preference)
        values = frame[chosen["name"]]
        return {
            "available": True,
            "column": chosen["name"],
            "kind": "datetime",
            "reason": f"'{chosen['name']}' contains dates/times for {100 - chosen['missing_pct']:.0f}% of rows.",
            "is_sorted": bool(values.dropna().is_monotonic_increasing),
            "duplicate_timestamps": int(values.dropna().duplicated().sum()),
            "start": to_jsonable(values.min()),
            "end": to_jsonable(values.max()),
        }

    for column in columns:
        tokens = set(name_tokens(column["name"]))
        if column["kind"] in ("numeric", "identifier") and SEQUENCE_TOKENS & tokens:
            values = frame[column["name"]].dropna()
            if len(values) >= 10 and values.is_monotonic_increasing and values.is_unique:
                return {
                    "available": True,
                    "column": column["name"],
                    "kind": "sequence",
                    "reason": f"'{column['name']}' is a strictly increasing sequence number. "
                              "Order is known, but real time intervals are not.",
                    "is_sorted": True,
                    "duplicate_timestamps": 0,
                    "start": to_jsonable(values.iloc[0]),
                    "end": to_jsonable(values.iloc[-1]),
                }

    return {
        "available": False,
        "reason": "No date/time column or sequence column was found. Row order alone is not "
                  "treated as time, so trend and drift analysis are skipped.",
    }


def _quality_indicators(overview: dict, columns: list[dict], cleaning_log: list[dict]) -> list[dict]:
    indicators = []

    def add(name: str, level: str, message: str, value=None) -> None:
        indicators.append({"indicator": name, "level": level, "message": message, "value": value})

    missing = overview["missing_pct"]
    add("Missing values", "ok" if missing < 1 else "notice" if missing < 10 else "warning",
        f"{missing:.2f}% of all cells are empty.", missing)
    duplicates = overview["duplicate_rows"]
    add("Duplicate rows", "ok" if duplicates == 0 else "notice" if overview["duplicate_pct"] < 5 else "warning",
        f"{duplicates:,} row(s) are exact copies of another row.", duplicates)

    for kind, label in (("empty", "Empty columns"), ("constant", "Constant columns")):
        names = [column["name"] for column in columns if column["kind"] == kind]
        if names:
            add(label, "notice", f"{', '.join(names)}: excluded from analysis.", len(names))
    high_missing = [column["name"] for column in columns if column["missing_pct"] >= 50 and column["kind"] != "empty"]
    if high_missing:
        add("Mostly-missing columns", "warning",
            f"{', '.join(high_missing)}: at least half the values are missing; excluded from detection.",
            len(high_missing))
    failed = [entry for entry in cleaning_log if entry.get("failed_values")]
    if failed:
        add("Conversion problems", "notice",
            "; ".join(f"{entry['column']}: {entry['failed_values']} value(s) unreadable" for entry in failed),
            sum(entry["failed_values"] for entry in failed))
    return indicators


def prepare_and_profile(raw: pd.DataFrame, size_bytes: int | None = None) -> tuple[dict, pd.DataFrame]:
    """Build the profile and the typed frame used by every later analysis step."""
    cleaning_log: list[dict] = []
    typed_columns = {}
    columns = []
    for name in raw.columns:
        typed, kind, roles, notes = _classify(name, raw[name], len(raw), cleaning_log)
        typed_columns[name] = typed
        columns.append(_describe_column(name, raw[name], typed, kind, roles, notes))
    frame = pd.DataFrame(typed_columns, index=raw.index)

    total_cells = raw.size
    missing_cells = int(frame.isna().sum().sum())
    duplicate_rows = int(raw.duplicated().sum())
    kind_counts: dict[str, int] = {}
    for column in columns:
        kind_counts[column["kind"]] = kind_counts.get(column["kind"], 0) + 1

    overview = {
        "rows": int(len(raw)),
        "columns": int(len(raw.columns)),
        "size_bytes": size_bytes,
        "memory_bytes": int(raw.memory_usage(deep=True).sum()),
        "missing_cells": missing_cells,
        "missing_pct": round(100 * missing_cells / total_cells, 2) if total_cells else 0.0,
        "duplicate_rows": duplicate_rows,
        "duplicate_pct": round(100 * duplicate_rows / len(raw), 2) if len(raw) else 0.0,
        "kind_counts": kind_counts,
    }
    profile = {
        "overview": overview,
        "columns": columns,
        "cleaning_log": cleaning_log,
        "cleaning_note": "The uploaded file is never modified and no rows are removed. "
                         "Conversions below apply to the analysis copy only.",
        "quality": _quality_indicators(overview, columns, cleaning_log),
        "correlations": _correlations(frame, columns),
        "time_axis": select_time_axis(frame, columns),
    }
    return to_jsonable(profile), frame
