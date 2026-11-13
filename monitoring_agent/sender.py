"""Sends metric batches to the NexusRaid backend, buffering while it is unreachable.

Uses only the Python standard library (urllib), so the agent needs just psutil.
"""

import json
import logging
import urllib.error
import urllib.request
from collections import deque

logger = logging.getLogger("nexusraid-agent")
MAX_BATCH = 500
AGENT_VERSION = "0.1.0"


class MetricSender:
    def __init__(self, endpoint: str, token: str, machine_id: str, hostname: str, interval_seconds: int,
                 max_buffer: int = 2000, timeout: float = 10.0):
        self.endpoint = endpoint
        self.token = token
        self.machine_id = machine_id
        self.hostname = hostname
        self.interval_seconds = interval_seconds
        self.timeout = timeout
        # Oldest samples are dropped first if the server is down for a long time.
        self.buffer: deque = deque(maxlen=max_buffer)
        self.dropped_invalid = 0

    def add(self, sample: dict) -> None:
        if len(self.buffer) == self.buffer.maxlen:
            logger.warning("Buffer full: the oldest sample is being discarded.")
        self.buffer.append(sample)

    def flush(self) -> bool:
        """Try to send everything buffered. Returns True when the buffer is empty afterwards."""
        while self.buffer:
            batch = list(self.buffer)[:MAX_BATCH]
            status, body = self._post(batch)
            if status is not None and 200 <= status < 300:
                for _ in batch:
                    self.buffer.popleft()
                logger.info("Sent %d sample(s): %s", len(batch), body)
                continue
            if status == 422:
                # The server rejected the data itself; resending would fail forever.
                for _ in batch:
                    self.buffer.popleft()
                self.dropped_invalid += len(batch)
                logger.error("Server rejected %d sample(s) as invalid: %s", len(batch), body)
                continue
            if status in (401, 403):
                logger.error("Authentication failed (%s). Check NEXUSRAID_AGENT_TOKEN. Keeping samples.", status)
            elif status == 503:
                logger.error("Server says ingestion is disabled: %s", body)
            else:
                logger.warning("Could not reach %s (%s). %d sample(s) buffered.", self.endpoint,
                               status or body, len(self.buffer))
            return False
        return True

    def _post(self, samples: list[dict]) -> tuple[int | None, str]:
        payload = json.dumps({
            "machine_id": self.machine_id, "hostname": self.hostname, "agent_version": AGENT_VERSION,
            "interval_seconds": self.interval_seconds, "samples": samples,
        }).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=payload, method="POST", headers={
            "Content-Type": "application/json", "X-Agent-Token": self.token,
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read(2000).decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read(2000).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            return None, str(getattr(error, "reason", error))
