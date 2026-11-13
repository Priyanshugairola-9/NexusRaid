from datetime import datetime, timedelta

import numpy as np

from app.services import monitoring_rules as rules

THRESHOLDS = {"cpu": [80, 95], "memory": [85, 95], "disk": [85, 95]}


def test_threshold_alerts():
    alerts = rules.threshold_alerts({"cpu_percent": 96, "memory_percent": 86, "disk_percent": 10}, THRESHOLDS)
    assert {(a["metric"], a["severity"]) for a in alerts} == {("cpu_percent", "critical"), ("memory_percent", "warning")}


def test_statistical_alert_needs_history_and_a_real_jump():
    history = {"cpu_percent": list(np.random.default_rng(0).normal(20, 3, 60))}
    assert rules.statistical_alerts({"cpu_percent": 70}, history, 6)
    assert not rules.statistical_alerts({"cpu_percent": 24}, history, 6)
    assert not rules.statistical_alerts({"cpu_percent": 70}, {"cpu_percent": [20.0] * 5}, 6)


def test_cooldown_and_escalation():
    now = datetime(2026, 1, 1, 12)
    recent = now - timedelta(seconds=60)
    assert rules.should_create("warning", None, None, now, 900)
    assert not rules.should_create("warning", recent, "warning", now, 900)
    assert rules.should_create("critical", recent, "warning", now, 900)
    assert rules.should_create("warning", now - timedelta(hours=1), "warning", now, 900)


def test_machine_state():
    timeout = rules.heartbeat_timeout(5, 3, 60)
    assert timeout == 60
    assert rules.machine_state({"cpu_percent": 50}, 10, timeout, THRESHOLDS)[0] == "normal"
    assert rules.machine_state({"cpu_percent": 90}, 10, timeout, THRESHOLDS)[0] == "warning"
    assert rules.machine_state({"cpu_percent": 99}, 10, timeout, THRESHOLDS)[0] == "critical"
    assert rules.machine_state({"cpu_percent": 50}, 61, timeout, THRESHOLDS)[0] == "unknown"
    assert rules.machine_state(None, None, timeout, THRESHOLDS)[0] == "unknown"
