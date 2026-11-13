"""Collects real system metrics with psutil.

Only what psutil can actually measure is collected. Application response
times and error counts need instrumentation inside the application and are
deliberately NOT faked here.

Disk and network I/O are cumulative counters in the operating system, so the
collector reports the change per second since the previous sample.
"""

import time
from datetime import datetime, timezone

import psutil


class MetricCollector:
    def __init__(self, metrics: tuple[str, ...], disk_path: str):
        self.metrics = set(metrics)
        self.disk_path = disk_path
        # cpu_percent(None) compares with the previous call, so the first call only primes it.
        psutil.cpu_percent(interval=None)
        self._last_time = time.monotonic()
        self._last_disk = self._safe(psutil.disk_io_counters)
        self._last_net = self._safe(psutil.net_io_counters)

    @staticmethod
    def _safe(function):
        try:
            return function()
        except (OSError, RuntimeError, AttributeError):
            return None  # some systems / containers do not expose these counters

    @staticmethod
    def _rate(current, previous, field: str, elapsed: float):
        if current is None or previous is None or elapsed <= 0:
            return None
        delta = getattr(current, field) - getattr(previous, field)
        return round(delta / elapsed, 1) if delta >= 0 else None  # counter reset -> skip one value

    def collect(self) -> dict:
        now = time.monotonic()
        elapsed = now - self._last_time
        self._last_time = now
        sample: dict = {"timestamp": datetime.now(timezone.utc).isoformat()}
        if "cpu" in self.metrics:
            sample["cpu_percent"] = psutil.cpu_percent(interval=None)
        if "memory" in self.metrics:
            sample["memory_percent"] = psutil.virtual_memory().percent
        if "disk" in self.metrics:
            try:
                sample["disk_percent"] = psutil.disk_usage(self.disk_path).percent
            except OSError:
                sample["disk_percent"] = None
        if "disk_io" in self.metrics:
            current = self._safe(psutil.disk_io_counters)
            sample["disk_read_bytes_per_sec"] = self._rate(current, self._last_disk, "read_bytes", elapsed)
            sample["disk_write_bytes_per_sec"] = self._rate(current, self._last_disk, "write_bytes", elapsed)
            self._last_disk = current
        if "network" in self.metrics:
            current = self._safe(psutil.net_io_counters)
            sample["net_sent_bytes_per_sec"] = self._rate(current, self._last_net, "bytes_sent", elapsed)
            sample["net_recv_bytes_per_sec"] = self._rate(current, self._last_net, "bytes_recv", elapsed)
            self._last_net = current
        if "processes" in self.metrics:
            sample["process_count"] = len(psutil.pids())
        return sample
