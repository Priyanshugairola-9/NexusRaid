"""End-to-end checks of the analysis engine on the synthetic samples."""

import json

import numpy as np
import pandas as pd

from helpers import analyse_frame, analyse_sample


def titles(results):
    return [finding["title"] for finding in results["findings"]]


def test_server_degradation_is_high_risk_but_not_critical_without_hard_limits():
    results = analyse_sample("server_metrics_synthetic.csv")
    assert results["risk"]["available"] is True
    assert results["risk"]["level"] == "High"
    assert all(signal["score"] <= 2 for signal in results["risk"]["signals"] if "trend" in signal["name"])


def test_latency_slo_enables_absolute_judgement():
    plain = analyse_sample("website_performance_synthetic.csv")
    with_slo = analyse_sample("website_performance_synthetic.csv", {"risk_thresholds": {"latency_ms": [300, 500]}})
    order = ["Low", "Medium", "High", "Critical"]
    assert order.index(with_slo["risk"]["level"]) > order.index(plain["risk"]["level"])


def test_financial_and_student_data_get_no_risk_score():
    for name in ("financial_transactions_synthetic.csv", "student_performance_synthetic.csv",
                 "network_traffic_synthetic.csv", "general_unknown_synthetic.csv"):
        risk = analyse_sample(name)["risk"]
        assert risk["available"] is False
        assert risk["message"] == "Risk assessment unavailable for this dataset."


def test_no_finding_calls_anything_fraud_or_an_attack():
    for name in ("financial_transactions_synthetic.csv", "network_traffic_synthetic.csv"):
        text = json.dumps(analyse_sample(name)["findings"]).lower()
        assert "is fraud" not in text and "attack detected" not in text


def test_domain_checks_find_the_injected_patterns():
    assert any("ACC-0007" in title for title in titles(analyse_sample("financial_transactions_synthetic.csv")))
    assert any("10.0.0.66" in title for title in titles(analyse_sample("network_traffic_synthetic.csv")))
    student = titles(analyse_sample("student_performance_synthetic.csv"))
    assert sum("impossible value" in title for title in student) == 3
    iot = titles(analyse_sample("iot_sensor_synthetic.csv"))
    assert any("humidity_pct repeated the same value" in title for title in iot)


def test_every_finding_answers_the_explainability_questions():
    required = {"what_happened", "columns", "observed", "comparison", "why_flagged", "method", "could_indicate",
                "confidence", "needs", "next_steps"}
    for finding in analyse_sample("server_metrics_synthetic.csv")["findings"]:
        assert required <= set(finding)
        assert finding["confidence"]["level"] in ("low", "medium", "high")


def test_results_are_json_serialisable_and_plan_explains_exclusions():
    results = analyse_sample("student_performance_synthetic.csv")
    json.dumps(results)
    excluded = {item["column"]: item["reason"] for item in results["plan"]["excluded_columns"]}
    assert "leak" in excluded["final_result"]


def test_degenerate_inputs_do_not_crash():
    for frame in (pd.DataFrame({"a": [1]}), pd.DataFrame({"a": ["x", "y"] * 10}),
                  pd.DataFrame({"a": [np.nan] * 10, "b": range(10)})):
        results = analyse_frame(frame)
        assert results["summary"]["lines"]
