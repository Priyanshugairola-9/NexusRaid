"""Small helpers shared by the analysis modules."""

import math
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def name_tokens(column_name: str) -> list[str]:
    """Split a column name into lowercase words.

    "cpuUsage_pct" -> ["cpu", "usage", "pct"];  "Response-Time (ms)" -> ["response", "time", "ms"]
    """
    spaced = _CAMEL_BOUNDARY.sub(r"\1 \2", str(column_name))
    return [token.lower() for token in _NON_ALNUM.split(spaced) if token]


def to_jsonable(value):
    """Convert numpy/pandas values into plain JSON-safe Python values.

    NaN and infinity become None, because JSON cannot represent them.
    """
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(item) for item in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value if isinstance(value, str) else str(value)


def round_or_none(value, digits: int = 4):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if math.isfinite(number) else None


def robust_center_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and a robust standard-deviation estimate (1.4826 x MAD).

    Unlike mean and std, these are barely moved by the outliers we are trying
    to find. Falls back to IQR / 1.349, then to std, when MAD is zero.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0, 0.0
    median = float(np.median(values))
    scale = 1.4826 * float(np.median(np.abs(values - median)))
    if scale == 0:
        q1, q3 = np.percentile(values, [25, 75])
        scale = float(q3 - q1) / 1.349
    if scale == 0:
        scale = float(np.std(values))
    return median, scale


def format_number(value, digits: int = 2) -> str:
    """Readable number for explanations: 1234567.8 -> '1,234,567.80'."""
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    if number == int(number) and abs(number) < 1e15:
        return f"{int(number):,}"
    if abs(number) >= 100:
        return f"{number:,.1f}"
    return f"{number:,.{digits}f}"
