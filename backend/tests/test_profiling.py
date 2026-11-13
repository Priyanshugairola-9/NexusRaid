import numpy as np
import pandas as pd

from app.services.profiling import numeric_feature_columns, prepare_and_profile


def kinds(profile):
    return {column["name"]: column["kind"] for column in profile["columns"]}


def test_column_kinds_are_inferred():
    frame = pd.DataFrame({
        "transaction_id": [f"T{i}" for i in range(40)],
        "timestamp": pd.date_range("2026-01-01", periods=40, freq="h").astype(str),
        "device_id": ["a", "b"] * 20,
        "amount": np.linspace(1, 100, 40),
        "flag": [0, 1] * 20,
        "notes": ["x" * 50 + str(i) for i in range(40)],
        "constant": [7] * 40,
        "empty": [np.nan] * 40,
        "dst_port": [443, 80] * 20,
    })
    profile, _ = prepare_and_profile(frame)
    assert kinds(profile) == {
        "transaction_id": "identifier", "timestamp": "datetime", "device_id": "categorical", "amount": "numeric",
        "flag": "boolean", "notes": "text", "constant": "constant", "empty": "empty", "dst_port": "categorical",
    }


def test_percent_strings_are_converted_and_logged():
    frame = pd.DataFrame({"cpu": ["10%", "20%", "30%"] * 10})
    profile, typed = prepare_and_profile(frame)
    assert typed["cpu"].iloc[1] == 20.0
    assert "% signs" in profile["cleaning_log"][0]["action"]


def test_unconvertible_values_are_counted_not_dropped():
    values = [str(i) for i in range(99)] + ["n/a"]
    profile, typed = prepare_and_profile(pd.DataFrame({"v": values}))
    assert len(typed) == 100
    assert profile["cleaning_log"][0]["failed_values"] == 1
    assert profile["columns"][0]["missing"] == 1


def test_infinite_values_become_missing_and_are_logged():
    profile, _ = prepare_and_profile(pd.DataFrame({"v": [1.0, np.inf, -np.inf] + list(range(30))}))
    assert profile["columns"][0]["missing"] == 2
    assert "infinite" in profile["cleaning_log"][0]["action"]


def test_missing_values_and_duplicates_are_reported():
    frame = pd.DataFrame({"a": [1, 1, np.nan, 4], "b": ["x", "x", "y", "z"]})
    profile, _ = prepare_and_profile(frame)
    assert profile["overview"]["duplicate_rows"] == 1
    assert profile["columns"][0]["missing"] == 1


def test_numeric_statistics():
    profile, _ = prepare_and_profile(pd.DataFrame({"v": [1, 2, 3, 4, 100]}))
    column = profile["columns"][0]
    assert column["median"] == 3
    assert column["max"] == 100
    assert sum(column["histogram"]["counts"]) == 5


def test_label_columns_are_not_features():
    frame = pd.DataFrame({"is_fraud": [0, 1] * 20, "amount": np.linspace(5, 90, 40) ** 1.5,
                          "final_result": ["Pass", "Fail"] * 20})
    profile, _ = prepare_and_profile(frame)
    assert numeric_feature_columns(profile["columns"]) == ["amount"]
    roles = {column["name"]: column["roles"] for column in profile["columns"]}
    assert "label_candidate" in roles["is_fraud"] and "label_candidate" in roles["final_result"]


def test_row_order_is_never_used_as_time():
    profile, _ = prepare_and_profile(pd.DataFrame({"a": range(50), "b": range(50)}))
    assert profile["time_axis"]["available"] is False


def test_unix_epoch_column_becomes_time_axis():
    frame = pd.DataFrame({"timestamp": 1_767_225_600 + np.arange(30) * 60, "cpu": range(30)})
    profile, _ = prepare_and_profile(frame)
    assert profile["time_axis"]["column"] == "timestamp"


def test_correlation_uses_spearman_and_lists_strong_pairs():
    x = np.linspace(0.5, 10, 100)
    profile, _ = prepare_and_profile(pd.DataFrame({"x": x, "y": x ** 3, "z": np.random.default_rng(0).random(100)}))
    pairs = profile["correlations"]["strong_pairs"]
    assert profile["correlations"]["method"] == "spearman"
    assert pairs[0]["a"] == "x" and pairs[0]["b"] == "y" and pairs[0]["rho"] == 1.0
