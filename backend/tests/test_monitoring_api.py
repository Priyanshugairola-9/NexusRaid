"""Monitoring API tests (need FastAPI installed)."""

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings

API = "/api/v1/monitoring"
TOKEN = {"X-Agent-Token": "test-agent-token"}


def batch(machine_id, samples, interval=15):
    return {"machine_id": machine_id, "hostname": "host", "agent_version": "0.1.0",
            "interval_seconds": interval, "samples": samples}


def samples(count, start_minutes_ago=30, cpu=20.0, step_seconds=15):
    start = datetime.now(timezone.utc) - timedelta(minutes=start_minutes_ago)
    return [{"timestamp": (start + timedelta(seconds=i * step_seconds)).isoformat(), "cpu_percent": cpu + (i % 5),
             "memory_percent": 50.0, "disk_percent": 60.0, "net_sent_bytes_per_sec": 1000.0 + i}
            for i in range(count)]


def test_agent_token_is_required(client):
    body = batch("m-auth", samples(1))
    assert client.post(f"{API}/metrics", json=body).status_code == 401
    assert client.post(f"{API}/metrics", json=body, headers={"X-Agent-Token": "wrong"}).status_code == 401


def test_ingestion_disabled_without_server_token(client):
    settings = get_settings()
    settings.agent_token = ""
    try:
        response = client.post(f"{API}/metrics", json=batch("m-off", samples(1)), headers=TOKEN)
        assert response.status_code == 503 and response.json()["error"]["code"] == "monitoring_disabled"
    finally:
        settings.agent_token = "test-agent-token"


def test_ingest_status_history_and_duplicates(client):
    data = samples(60)
    first = client.post(f"{API}/metrics", json=batch("m-main", data), headers=TOKEN).json()
    assert first["accepted"] == 60 and first["duplicates"] == 0
    again = client.post(f"{API}/metrics", json=batch("m-main", data), headers=TOKEN).json()
    assert again["accepted"] == 0 and again["duplicates"] == 60

    machine = next(m for m in client.get(f"{API}/status").json()["machines"] if m["machine_id"] == "m-main")
    assert machine["state"] == "normal"
    assert machine["latest"]["cpu_percent"] is not None
    history = client.get(f"{API}/metrics", params={"machine_id": "m-main", "minutes": 60}).json()
    assert len(history["samples"]) == 60

    analysis = client.get(f"{API}/analysis", params={"machine_id": "m-main", "hours": 1})
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["domain"]["detected"] == "server"


def test_threshold_alert_and_cooldown(client):
    hot = samples(1, start_minutes_ago=1, cpu=97.0)
    created = client.post(f"{API}/metrics", json=batch("m-hot", hot), headers=TOKEN).json()
    assert created["alerts_created"] >= 1
    hot_again = samples(1, start_minutes_ago=0, cpu=97.0)
    repeat = client.post(f"{API}/metrics", json=batch("m-hot", hot_again), headers=TOKEN).json()
    assert repeat["alerts_created"] == 0  # same alert inside the cooldown window
    alerts = client.get(f"{API}/alerts", params={"machine_id": "m-hot"}).json()["alerts"]
    assert alerts[0]["severity"] == "critical" and alerts[0]["kind"] == "threshold"
    state = next(m for m in client.get(f"{API}/status").json()["machines"] if m["machine_id"] == "m-hot")
    assert state["state"] == "critical"


def test_invalid_and_out_of_range_samples(client):
    bad = samples(1)
    bad[0]["cpu_percent"] = 150
    assert client.post(f"{API}/metrics", json=batch("m-bad", bad), headers=TOKEN).status_code == 422
    assert client.post(f"{API}/metrics", json=batch("bad id!", samples(1)), headers=TOKEN).status_code == 422
    future = samples(1, start_minutes_ago=-60)
    result = client.post(f"{API}/metrics", json=batch("m-future", future), headers=TOKEN).json()
    assert result["rejected"] == 1 and result["accepted"] == 0


def test_silent_machine_becomes_unknown(client):
    client.post(f"{API}/metrics", json=batch("m-quiet", samples(1), interval=5), headers=TOKEN)
    settings = get_settings()
    original = settings.min_heartbeat_timeout_seconds
    settings.min_heartbeat_timeout_seconds = 10
    try:
        from app.database.connection import SessionLocal
        from app.database.models import MonitoredMachine
        with SessionLocal() as db:
            machine = db.query(MonitoredMachine).filter_by(machine_id="m-quiet").one()
            machine.last_seen = machine.last_seen - timedelta(minutes=5)
            db.commit()
        state = next(m for m in client.get(f"{API}/status").json()["machines"] if m["machine_id"] == "m-quiet")
        assert state["state"] == "unknown"
        kinds = [a["kind"] for a in client.get(f"{API}/alerts", params={"machine_id": "m-quiet"}).json()["alerts"]]
        assert "heartbeat" in kinds
    finally:
        settings.min_heartbeat_timeout_seconds = original


def test_unknown_machine(client):
    assert client.get(f"{API}/metrics", params={"machine_id": "nobody"}).status_code == 404
