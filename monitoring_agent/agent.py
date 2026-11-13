"""NexusRaid monitoring agent.

Collects CPU, memory, disk, disk I/O, network I/O and process count every few
seconds and sends them to a NexusRaid backend. It must be started explicitly by
the machine's owner; a website cannot (and must not) read a visitor's computer.

Usage (from the monitoring_agent folder):
    set NEXUSRAID_AGENT_TOKEN=your-token        (PowerShell: $env:NEXUSRAID_AGENT_TOKEN="your-token")
    python agent.py --api-url http://127.0.0.1:8000
    python agent.py --dry-run --once            (print one sample, send nothing)
"""

import argparse
import json
import logging
import socket
import sys
import time

from agent_config import load_config
from collector import MetricCollector
from sender import MetricSender

MAX_BACKOFF_SECONDS = 300


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="NexusRaid monitoring agent")
    parser.add_argument("--config", help="Path to a JSON config file (see agent_config.example.json)")
    parser.add_argument("--api-url", help="Backend address, e.g. http://127.0.0.1:8000")
    parser.add_argument("--machine-id", help="Name for this machine (letters, digits, . _ -)")
    parser.add_argument("--interval", type=int, help="Seconds between samples (default 15)")
    parser.add_argument("--once", action="store_true", help="Collect one sample and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print samples instead of sending them")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("nexusraid-agent")
    args = parse_args(argv)
    overrides = {"api_url": args.api_url, "machine_id": args.machine_id, "interval_seconds": args.interval}
    try:
        config = load_config(args.config, {key: value for key, value in overrides.items() if value is not None})
    except (ValueError, OSError, json.JSONDecodeError) as error:
        log.error("Configuration error: %s", error)
        return 2
    if not config.token and not args.dry_run:
        log.error("No agent token. Set the NEXUSRAID_AGENT_TOKEN environment variable (same value as on the server).")
        return 2

    collector = MetricCollector(config.metrics, config.disk_path)
    sender = MetricSender(config.endpoint, config.token, config.machine_id, socket.gethostname(),
                          config.interval_seconds, config.max_buffer, config.timeout_seconds)
    log.info("Monitoring '%s' every %ss -> %s", config.machine_id, config.interval_seconds,
             "stdout (dry run)" if args.dry_run else config.endpoint)
    time.sleep(1)  # give cpu_percent a measurement window for the first sample

    failures = 0
    next_attempt = 0.0
    try:
        while True:
            started = time.monotonic()
            sample = collector.collect()
            if args.dry_run:
                print(json.dumps(sample), flush=True)
            else:
                sender.add(sample)
                if started >= next_attempt:
                    if sender.flush():
                        failures = 0
                        next_attempt = 0.0
                    else:
                        # Back off (15 s, 30 s, 60 s ... max 5 min) but keep collecting.
                        failures += 1
                        next_attempt = started + min(config.interval_seconds * 2 ** failures, MAX_BACKOFF_SECONDS)
            if args.once:
                return 0 if (args.dry_run or not sender.buffer) else 1
            time.sleep(max(0.0, config.interval_seconds - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("Stopping; trying to send %d buffered sample(s).", len(sender.buffer))
        if not args.dry_run:
            sender.flush()
        return 0


if __name__ == "__main__":
    sys.exit(main())
