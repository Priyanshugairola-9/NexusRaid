import numpy as np
import pandas as pd

from app.services.analysis_config import AnalysisConfig
from app.services.profiling import numeric_feature_columns, prepare_and_profile
from app.services.trend_analysis import analyze_trends
from helpers import load_sample, regular_series


def trends_for(frame):
    profile, typed = prepare_and_profile(frame)
    return analyze_trends(typed, profile, numeric_feature_columns(profile["columns"]), AnalysisConfig())


def result_for(trends, column):
    return next(item for item in trends.summary["results"] if item["column"] == column)


def test_no_time_axis_means_no_trends():
    trends = trends_for(pd.DataFrame({"a": range(100)}))
    assert trends.summary["available"] is False


def test_steady_increase_is_detected():
    frame = regular_series()
    frame["value"] = frame["value"] + np.linspace(0, 30, len(frame))
    assert result_for(trends_for(frame), "value")["direction"] == "increasing"


def test_flat_noise_is_stable():
    assert result_for(trends_for(regular_series()), "value")["direction"] == "stable"


def test_persistent_level_shift_is_found_but_a_short_burst_is_a_spike():
    frame = regular_series(seed=1)
    frame.loc[150:, "value"] += 25
    frame.loc[60:61, "value"] += 40
    result = result_for(trends_for(frame), "value")
    assert len(result["level_shifts"]) == 1
    assert result["level_shifts"][0]["direction"] == "up"
    assert len(result["spikes"]) >= 1


def test_noise_free_ramp_has_no_false_jumps():
    frame = regular_series()
    frame["value"] = np.linspace(55, 70, len(frame))
    result = result_for(trends_for(frame), "value")
    assert result["level_shifts"] == [] and result["spikes"] == []


def test_gaps_are_found_per_device():
    profile, frame = load_sample("iot_sensor_synthetic.csv")
    trends = analyze_trends(frame, profile, numeric_feature_columns(profile["columns"]), AnalysisConfig())
    assert trends.summary["mode"] == "grouped"
    assert [(gap["series"], gap["missing_points"]) for gap in trends.summary["gaps"]] == [("sensor-A", 24)]


def test_events_are_bucketed():
    profile, frame = load_sample("financial_transactions_synthetic.csv")
    trends = analyze_trends(frame, profile, numeric_feature_columns(profile["columns"]), AnalysisConfig())
    assert trends.summary["mode"] == "events"
    assert "events per bucket" in trends.summary["columns"]


def test_co_movement_is_reported_without_claiming_cause():
    profile, frame = load_sample("server_metrics_synthetic.csv")
    trends = analyze_trends(frame, profile, numeric_feature_columns(profile["columns"]), AnalysisConfig())
    rising = trends.summary["co_movement"]["increasing"]
    assert {"cpu_usage", "memory_usage", "response_time_ms", "error_count"} <= set(rising)
    assert "does not show" in trends.summary["co_movement"]["note"]
