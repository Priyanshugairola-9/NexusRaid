"""Generate the SYNTHETIC sample datasets used for demos and tests.

Every file produced here is artificial. The patterns injected into each file
are listed in INJECTED_PATTERNS so tests (and you) can check whether NexusRaid
finds what was actually put there. Nothing here is real-world data.

Run from the repository root:
    python samples/generate_samples.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SAMPLES_DIR = Path(__file__).resolve().parent
SEED = 42

# What was deliberately put into each file (used by tests and the README).
INJECTED_PATTERNS = {
    "server_metrics_synthetic.csv": [
        "5 isolated CPU spikes (rows 100, 220, 340, 460, 560)",
        "gradual stress from row 650: CPU, memory, response time and errors rise together",
        "disk usage grows slowly and steadily for the whole period",
    ],
    "network_traffic_synthetic.csv": [
        "burst of short connections from 10.0.0.66 to many ports between 14:00 and 14:10",
        "8 very large transfers (bytes_sent)",
    ],
    "iot_sensor_synthetic.csv": [
        "temperature spikes marked in anomaly_label = 1",
        "sensor-B temperature drifts upward over the last day",
        "sensor-C humidity stuck at one value for 6 hours",
        "sensor-A has a 4-hour gap with no readings",
    ],
    "website_performance_synthetic.csv": [
        "latency degrades during the last 3 hours",
        "error spike between 09:00 and 09:15",
    ],
    "financial_transactions_synthetic.csv": [
        "6 very large transaction amounts",
        "account ACC-0007 makes a burst of 40 transactions within one hour",
    ],
    "student_performance_synthetic.csv": [
        "3 data-entry errors: scores above 100",
        "final_result is an outcome column and must not be used as a feature",
    ],
    "general_unknown_synthetic.csv": [
        "no recognisable domain; 4 plants with unusually large height",
    ],
}


def server_metrics(rng: np.random.Generator) -> pd.DataFrame:
    n = 864  # 3 days at 5-minute intervals
    time = pd.date_range("2026-03-01 00:00", periods=n, freq="5min")
    hour = time.hour.to_numpy() + time.minute.to_numpy() / 60
    daily = np.sin((hour - 6) / 24 * 2 * np.pi)  # gentle day/night cycle

    cpu = 38 + 8 * daily + rng.normal(0, 3, n)
    memory = 52 + 3 * daily + rng.normal(0, 1.5, n)
    disk = np.linspace(61, 70, n) + rng.normal(0, 0.15, n)
    net_in = 120 + 30 * daily + rng.normal(0, 10, n)
    response = 110 + 15 * daily + rng.normal(0, 8, n)
    errors = rng.poisson(1.0, n).astype(float)

    stress = np.zeros(n)
    stress[650:] = np.linspace(0, 1, n - 650)  # gradual degradation
    cpu += 40 * stress
    memory += 32 * stress
    response += 520 * stress**1.5
    errors += rng.poisson(1 + 14 * stress) - 1

    for row in (100, 220, 340, 460, 560):
        cpu[row] = rng.uniform(93, 98)

    return pd.DataFrame({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_usage": np.clip(cpu, 0, 100).round(1),
        "memory_usage": np.clip(memory, 0, 100).round(1),
        "disk_usage": disk.round(2),
        "network_in_mbps": np.clip(net_in, 0, None).round(1),
        "response_time_ms": np.clip(response, 5, None).round(0),
        "error_count": np.clip(errors, 0, None).astype(int),
    })


def network_traffic(rng: np.random.Generator) -> pd.DataFrame:
    n = 3000
    seconds = np.sort(rng.uniform(0, 24 * 3600, n))
    time = pd.Timestamp("2026-03-05") + pd.to_timedelta(seconds, unit="s")
    src = rng.choice([f"10.0.0.{i}" for i in range(2, 30)], n)
    dst = rng.choice(["172.16.0.10", "172.16.0.11", "172.16.0.20", "8.8.8.8"], n)
    port = rng.choice([443, 80, 53, 22, 3306], n, p=[0.6, 0.2, 0.12, 0.05, 0.03])
    proto = np.where(port == 53, "UDP", "TCP")
    sent = rng.lognormal(8, 1, n).round(0)
    received = (sent * rng.uniform(2, 10, n)).round(0)
    packets = np.maximum(1, (sent + received) / 900).round(0)
    duration = rng.lognormal(5, 0.8, n).round(1)
    frame = pd.DataFrame({
        "timestamp": time, "src_ip": src, "dst_ip": dst, "dst_port": port,
        "protocol": proto, "bytes_sent": sent, "bytes_received": received,
        "packets": packets, "duration_ms": duration,
    })

    burst_n = 300
    burst_time = pd.Timestamp("2026-03-05 14:00") + pd.to_timedelta(
        np.sort(rng.uniform(0, 600, burst_n)), unit="s")
    burst = pd.DataFrame({
        "timestamp": burst_time, "src_ip": "10.0.0.66", "dst_ip": "172.16.0.20",
        "dst_port": rng.integers(1000, 9000, burst_n), "protocol": "TCP",
        "bytes_sent": rng.integers(40, 80, burst_n).astype(float),
        "bytes_received": 0.0, "packets": 1.0,
        "duration_ms": rng.uniform(0.5, 2, burst_n).round(1),
    })
    frame = pd.concat([frame, burst], ignore_index=True)
    big = rng.choice(len(frame) - burst_n, 8, replace=False)
    frame.loc[big, "bytes_sent"] = rng.uniform(5e7, 9e7, 8).round(0)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame


def iot_sensors(rng: np.random.Generator) -> pd.DataFrame:
    parts = []
    time = pd.date_range("2026-03-10 00:00", periods=432, freq="10min")  # 3 days
    hour = time.hour.to_numpy() + time.minute.to_numpy() / 60
    for device, base in (("sensor-A", 22.0), ("sensor-B", 24.0), ("sensor-C", 21.0)):
        n = len(time)
        temp = base + 2.5 * np.sin((hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.3, n)
        humidity = 45 + 5 * np.cos(hour / 24 * 2 * np.pi) + rng.normal(0, 1, n)
        pressure = 1013 + rng.normal(0, 1.2, n)
        battery = np.linspace(3.9, 3.7, n) + rng.normal(0, 0.01, n)
        label = np.zeros(n, dtype=int)

        spikes = rng.choice(np.arange(20, n - 20), 3, replace=False)
        temp[spikes] += rng.uniform(15, 20, 3)
        label[spikes] = 1
        if device == "sensor-B":
            temp[-144:] += np.linspace(0, 6, 144)  # last day drifts upward
        if device == "sensor-C":
            humidity[200:236] = 51.2  # stuck for 6 hours

        part = pd.DataFrame({
            "timestamp": time, "device_id": device, "temperature_c": temp.round(2),
            "humidity_pct": humidity.round(1), "pressure_hpa": pressure.round(1),
            "battery_v": battery.round(3), "anomaly_label": label,
        })
        if device == "sensor-A":
            part = part.drop(index=range(120, 144))  # 4-hour gap
        parts.append(part)
    frame = pd.concat(parts).sort_values(["timestamp", "device_id"]).reset_index(drop=True)
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return frame


def website_performance(rng: np.random.Generator) -> pd.DataFrame:
    n = 720  # 12 hours at 1-minute intervals
    time = pd.date_range("2026-03-12 06:00", periods=n, freq="1min")
    requests = rng.poisson(900 + 300 * np.sin(np.arange(n) / n * np.pi), n)
    latency = 180 + rng.normal(0, 15, n)
    latency[-180:] += np.linspace(0, 450, 180)
    p95 = latency * rng.uniform(1.8, 2.2, n)
    errors = rng.binomial(requests, 0.004)
    errors[180:196] = rng.binomial(requests[180:196], 0.08)
    return pd.DataFrame({
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        "request_count": requests,
        "avg_response_time_ms": latency.round(1),
        "p95_latency_ms": p95.round(1),
        "error_count": errors,
    })


def financial_transactions(rng: np.random.Generator) -> pd.DataFrame:
    n = 5000
    seconds = np.sort(rng.uniform(0, 30 * 24 * 3600, n))
    time = pd.Timestamp("2026-02-01") + pd.to_timedelta(seconds, unit="s")
    accounts = rng.choice([f"ACC-{i:04d}" for i in range(1, 201)], n)
    amount = rng.lognormal(3.6, 0.9, n).round(2)
    frame = pd.DataFrame({
        "transaction_id": [f"TX{100000 + i}" for i in range(n)],
        "timestamp": time,
        "account_id": accounts,
        "merchant_category": rng.choice(
            ["grocery", "fuel", "electronics", "restaurant", "travel", "utilities"], n,
            p=[0.3, 0.15, 0.1, 0.25, 0.05, 0.15]),
        "channel": rng.choice(["card", "upi", "netbanking"], n, p=[0.5, 0.4, 0.1]),
        "amount": amount,
    })
    big = rng.choice(n, 6, replace=False)
    frame.loc[big, "amount"] = rng.uniform(25000, 60000, 6).round(2)

    burst_time = pd.Timestamp("2026-02-18 02:00") + pd.to_timedelta(
        np.sort(rng.uniform(0, 3600, 40)), unit="s")
    burst = pd.DataFrame({
        "transaction_id": [f"TX{200000 + i}" for i in range(40)],
        "timestamp": burst_time, "account_id": "ACC-0007",
        "merchant_category": "electronics", "channel": "card",
        "amount": rng.uniform(80, 120, 40).round(2),
    })
    frame = pd.concat([frame, burst]).sort_values("timestamp").reset_index(drop=True)
    frame["timestamp"] = frame["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return frame


def student_performance(rng: np.random.Generator) -> pd.DataFrame:
    n = 400
    ability = rng.normal(0, 1, n)
    attendance = np.clip(80 + 8 * ability + rng.normal(0, 6, n), 35, 100)
    study = np.clip(8 + 3 * ability + rng.normal(0, 2, n), 0, 30)

    def subject(weight: float) -> np.ndarray:
        return np.clip(62 + 12 * weight * ability + rng.normal(0, 8, n), 0, 100)

    frame = pd.DataFrame({
        "student_id": [f"S{2026000 + i}" for i in range(n)],
        "attendance_pct": attendance.round(1),
        "study_hours_per_week": study.round(1),
        "math_score": subject(1.1).round(0),
        "science_score": subject(1.0).round(0),
        "english_score": subject(0.7).round(0),
        "history_score": subject(0.6).round(0),
    })
    for row, col in ((15, "math_score"), (160, "english_score"), (333, "science_score")):
        frame.loc[row, col] = rng.choice([185, 156, 210])
    avg = frame[["math_score", "science_score", "english_score", "history_score"]].mean(axis=1)
    frame["final_result"] = np.where(avg >= 50, "Pass", "Fail")
    return frame


def general_unknown(rng: np.random.Generator) -> pd.DataFrame:
    n = 300
    sunlight = rng.uniform(3, 10, n)
    water = rng.normal(250, 40, n)
    height = 10 + 2.2 * sunlight + 0.03 * water + rng.normal(0, 2, n)
    height[[30, 90, 150, 270]] = rng.uniform(70, 90, 4)
    return pd.DataFrame({
        "plot_code": [f"P-{i:03d}" for i in range(n)],
        "species": rng.choice(["fern", "basil", "mint", "tulsi"], n),
        "sunlight_hours": sunlight.round(1),
        "water_ml": water.round(0),
        "height_cm": height.round(1),
        "leaf_count": rng.poisson(20 + sunlight * 2).astype(int),
    })


GENERATORS = {
    "server_metrics_synthetic.csv": server_metrics,
    "network_traffic_synthetic.csv": network_traffic,
    "iot_sensor_synthetic.csv": iot_sensors,
    "website_performance_synthetic.csv": website_performance,
    "financial_transactions_synthetic.csv": financial_transactions,
    "student_performance_synthetic.csv": student_performance,
    "general_unknown_synthetic.csv": general_unknown,
}


def main() -> None:
    for offset, (filename, generator) in enumerate(GENERATORS.items()):
        frame = generator(np.random.default_rng(SEED + offset))
        frame.to_csv(SAMPLES_DIR / filename, index=False)
        print(f"{filename}: {len(frame)} rows, {len(frame.columns)} columns")


if __name__ == "__main__":
    main()
