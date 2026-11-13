import pandas as pd
import pytest

from app.services.domain_detection import detect_domain
from app.services.profiling import prepare_and_profile
from helpers import load_sample


@pytest.mark.parametrize("filename, expected", [
    ("server_metrics_synthetic.csv", "server"),
    ("network_traffic_synthetic.csv", "network"),
    ("iot_sensor_synthetic.csv", "iot"),
    ("website_performance_synthetic.csv", "website"),
    ("financial_transactions_synthetic.csv", "financial"),
    ("student_performance_synthetic.csv", "student"),
    ("general_unknown_synthetic.csv", "general"),
])
def test_samples_are_recognised(filename, expected):
    profile, frame = load_sample(filename)
    result = detect_domain(profile, frame)
    assert result["detected"] == expected
    if expected != "general":
        assert result["level"] == "strong"
        assert result["reasons"]


def test_partial_domain():
    values = [12.5, 30.1, 18.4, 22.0, 41.3, 25.6] * 5
    profile, frame = prepare_and_profile(pd.DataFrame({"cpu_load": values, "other": values[::-1]}))
    result = detect_domain(profile, frame)
    assert result["detected"] == "server"
    assert result["level"] == "partial"
    assert any("Missing core signals" in item for item in result["limitations"])


def test_unknown_dataset_is_not_forced_into_a_domain():
    profile, frame = prepare_and_profile(pd.DataFrame({"colour": ["red", "blue"] * 15, "size": [3.5, 1.2, 8.8] * 10}))
    result = detect_domain(profile, frame)
    assert result["detected"] == "general"
    assert result["outcome"] == "unknown"


def test_implausible_percentage_is_noted():
    profile, frame = prepare_and_profile(pd.DataFrame({"cpu_usage": [50, 300] * 15, "memory_usage": [40] * 29 + [41]}))
    result = detect_domain(profile, frame)
    assert any("outside 0-100" in item for item in result["limitations"])


def test_port_column_is_not_mistaken_for_destination():
    profile, frame = load_sample("network_traffic_synthetic.csv")
    roles = detect_domain(profile, frame)["matched_roles"]
    assert roles["port"] == ["dst_port"]
