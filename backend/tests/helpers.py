"""Helpers shared by the analysis-engine tests."""

from pathlib import Path

import numpy as np
import pandas as pd

from app.services.analysis_config import AnalysisConfig
from app.services.pipeline import run_analysis
from app.services.profiling import prepare_and_profile
from app.services.validation import UploadLimits, read_and_validate_csv

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
LIMITS = UploadLimits(max_bytes=25 * 1024 * 1024, max_rows=200_000, max_columns=200)


def load_sample(name: str):
    validated = read_and_validate_csv(SAMPLES_DIR / name, LIMITS)
    return prepare_and_profile(validated.frame)


def analyse_sample(name: str, config: dict | None = None) -> dict:
    profile, frame = load_sample(name)
    return run_analysis(profile, frame, AnalysisConfig.from_dict(config)).results


def analyse_frame(frame: pd.DataFrame) -> dict:
    profile, typed = prepare_and_profile(frame)
    return run_analysis(profile, typed).results


def write_csv(path: Path, text: str | bytes) -> Path:
    if isinstance(text, str):
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(text)
    return path


def regular_series(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="5min").strftime("%Y-%m-%d %H:%M:%S"),
        "value": rng.normal(50, 2, n),
    })
