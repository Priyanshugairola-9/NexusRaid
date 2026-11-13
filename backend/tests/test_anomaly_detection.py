import numpy as np
import pandas as pd

from app.services.analysis_config import AnalysisConfig
from app.services.anomaly_detection import choose_univariate_method, detect_anomalies
from app.services.profiling import numeric_feature_columns, prepare_and_profile
from helpers import load_sample


def run(frame, config=None):
    profile, typed = prepare_and_profile(frame)
    return detect_anomalies(typed, profile, numeric_feature_columns(profile["columns"]), config or AnalysisConfig())


def test_injected_outliers_are_found():
    rng = np.random.default_rng(1)
    values = rng.normal(100, 5, 500)
    values[[10, 200, 400]] = [200, 10, 190]
    result = run(pd.DataFrame({"v": values}))
    flagged = {record["row_number"] for record in result.records}
    assert {11, 201, 401} <= flagged


def test_clean_normal_data_produces_few_flags():
    rng = np.random.default_rng(2)
    result = run(pd.DataFrame({"a": rng.normal(size=2000), "b": rng.normal(size=2000)}))
    assert result.summary["flagged_pct"] < 1.0


def test_isolation_forest_threshold_does_not_force_a_quota():
    # A fixed 'contamination' would always flag a percentage; the robust threshold must not.
    rng = np.random.default_rng(3)
    result = run(pd.DataFrame({"a": rng.normal(size=1000), "b": rng.normal(size=1000), "c": rng.normal(size=1000)}))
    assert result.summary["multivariate"]["flagged_pct"] < 1.0


def test_method_selection_rules():
    rng = np.random.default_rng(4)
    assert choose_univariate_method(rng.normal(size=200), "auto")[0] == "modified_zscore"
    assert choose_univariate_method(rng.lognormal(3, 1, 200), "auto")[0] == "iqr_log"
    assert choose_univariate_method(np.arange(10.0), "auto")[0] is None
    assert choose_univariate_method(np.array([1.0, 2.0] * 50), "auto")[0] is None


def test_small_and_constant_data_are_skipped_safely():
    result = run(pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [7] * 5}))
    assert result.summary["flagged_rows"] == 0
    assert result.summary["multivariate"]["skipped"] is True


def test_identifier_columns_are_not_analysed():
    frame = pd.DataFrame({"student_id": [f"S{i}" for i in range(100)], "row_no": range(100),
                          "score": np.random.default_rng(5).normal(60, 5, 100)})
    assert run(frame).summary["features"] == ["score"]


def test_every_flagged_row_has_a_reason():
    result = run(pd.DataFrame({"v": list(np.random.default_rng(6).normal(0, 1, 300)) + [50.0]}))
    assert result.records
    assert all(record["reasons"] for record in result.records)


def test_label_validation_reports_precision_and_recall():
    profile, frame = load_sample("iot_sensor_synthetic.csv")
    result = detect_anomalies(frame, profile, numeric_feature_columns(profile["columns"]), AnalysisConfig(),
                              "timestamp")
    check = result.summary["label_validation"]
    assert check["available"] is True
    assert check["label_column"] == "anomaly_label"
    assert check["any_method"]["recall"] >= 0.7
