"""Agent tests. A tiny local HTTP server stands in for the NexusRaid backend.

Run from the monitoring_agent folder:  python -m pytest tests
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_config import default_disk_path, load_config
from collector import MetricCollector
from sender import MetricSender

TOKEN = "test-token"


class FakeBackend:
    def __init__(self):
        self.received = []
        self.mode = "ok"  # ok | invalid
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.headers.get("X-Agent-Token") != TOKEN:
                    status, reply = 401, {"error": "bad token"}
                elif backend.mode == "invalid":
                    status, reply = 422, {"error": "invalid"}
                else:
                    backend.received.append(body)
                    status, reply = 200, {"accepted": len(body["samples"])}
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v1/monitoring/metrics"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def backend():
    server = FakeBackend()
    yield server
    server.stop()


def make_sender(url, token=TOKEN):
    return MetricSender(url, token, "test-machine", "host", 15, max_buffer=50, timeout=2)


def test_collector_returns_real_metrics_in_valid_ranges():
    sample = MetricCollector(("cpu", "memory", "disk", "disk_io", "network", "processes"), default_disk_path()).collect()
    assert sample["timestamp"].endswith("+00:00")
    assert 0 <= sample["cpu_percent"] <= 100
    assert 0 <= sample["memory_percent"] <= 100
    assert sample["process_count"] > 0


def test_collector_only_collects_selected_metrics():
    sample = MetricCollector(("memory",), default_disk_path()).collect()
    assert set(sample) == {"timestamp", "memory_percent"}


def test_sender_delivers_buffered_samples(backend):
    sender = make_sender(backend.url)
    sender.add({"timestamp": "2026-01-01T00:00:00+00:00", "cpu_percent": 10})
    sender.add({"timestamp": "2026-01-01T00:00:15+00:00", "cpu_percent": 12})
    assert sender.flush() is True
    assert not sender.buffer
    assert backend.received[0]["machine_id"] == "test-machine"
    assert len(backend.received[0]["samples"]) == 2


def test_wrong_token_keeps_samples_for_later(backend):
    sender = make_sender(backend.url, token="wrong")
    sender.add({"timestamp": "2026-01-01T00:00:00+00:00"})
    assert sender.flush() is False
    assert len(sender.buffer) == 1
    assert backend.received == []


def test_unreachable_server_buffers_then_recovers(backend):
    url = backend.url
    backend.stop()  # server is down
    sender = make_sender(url)
    for second in range(3):
        sender.add({"timestamp": f"2026-01-01T00:00:0{second}+00:00"})
    assert sender.flush() is False
    assert len(sender.buffer) == 3

    revived = FakeBackend()
    try:
        sender.endpoint = revived.url
        assert sender.flush() is True
        assert len(revived.received[0]["samples"]) == 3
    finally:
        revived.stop()


def test_invalid_data_is_dropped_instead_of_retried_forever(backend):
    backend.mode = "invalid"
    sender = make_sender(backend.url)
    sender.add({"timestamp": "not-a-time"})
    assert sender.flush() is True
    assert sender.dropped_invalid == 1


def test_buffer_discards_oldest_when_full():
    sender = MetricSender("http://127.0.0.1:9/x", TOKEN, "m", "h", 15, max_buffer=10)
    for number in range(15):
        sender.add({"n": number})
    assert [item["n"] for item in sender.buffer][0] == 5


def test_config_rejects_bad_values(tmp_path):
    with pytest.raises(ValueError, match="machine_id"):
        load_config(overrides={"machine_id": "bad id!"})
    with pytest.raises(ValueError, match="Unknown metrics"):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"metrics": ["cpu", "gpu"]}))
        load_config(str(path))
    with pytest.raises(ValueError, match="api_url"):
        load_config(overrides={"api_url": "ftp://x"})
