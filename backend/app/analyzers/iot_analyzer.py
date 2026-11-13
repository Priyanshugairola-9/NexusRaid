"""IoT sensor data: readings per device, stuck sensors, drift, spikes and missing readings."""

import numpy as np
import pandas as pd

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import bounds_check, flatline, trend_signal

READING_ROLES = ("temperature", "humidity", "pressure", "vibration", "air", "light", "reading")
DEVICE_KINDS = ("categorical", "identifier")


class IoTAnalyzer(BaseAnalyzer):
    domain = "iot"
    title = "IoT sensor data"
    description = "Readings from sensors or devices over time."
    risk_supported = True
    risk_title = "Sensor health"
    roles = (
        Role("device", "Device", ("device*", "sensor", "sensor id", "node*", "station*", "gateway", "unit"),
             kinds=DEVICE_KINDS),
        Role("temperature", "Temperature", ("temp*",), direction="either"),
        Role("humidity", "Humidity", ("humid*", "rh", "moisture"), direction="either"),
        Role("pressure", "Pressure", ("pressure", "hpa", "kpa", "psi"), direction="either"),
        Role("vibration", "Vibration", ("vibration", "accel*", "acceleration", "gyro*"),
             direction="higher_is_worse"),
        Role("air", "Air quality", ("co2", "pm25", "pm2", "pm10", "voc", "gas", "aqi", "smoke"),
             direction="higher_is_worse"),
        Role("light", "Light", ("lux", "light", "illuminance")),
        Role("battery", "Battery", ("battery", "batt"), core=False, direction="lower_is_worse"),
        Role("signal", "Signal strength", ("rssi", "signal", "snr"), core=False, direction="lower_is_worse"),
        Role("electrical", "Electrical", ("volt*", "voltage", "current", "power"), core=False, direction="either"),
        Role("reading", "Reading", ("reading", "measurement"), core=False, direction="either"),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        device = ctx.first("device")
        group = device if device and ctx.column_profile(device)["kind"] == "categorical" else None
        if group:
            self._device_table(ctx, out, group)

        for column in ctx.roles.get("humidity", []):
            bounds_check(ctx, out, column, 0, 100, "relative humidity percentage")

        recent_cutoff = None
        if ctx.time_column:
            times = (ctx.frame[ctx.time_column] - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)
            recent_cutoff = times.min() + 0.9 * (times.max() - times.min())

        stuck_recent, stuck_any = [], []
        for role in READING_ROLES:
            for column in ctx.roles.get(role, [])[:3]:
                runs = flatline(ctx, out, column, group)
                if runs:
                    stuck_any.append(column)
                    if recent_cutoff is not None and any(run["end"] >= recent_cutoff for run in runs):
                        stuck_recent.append(column)
                out.risk_signals.append(trend_signal(ctx, column, self.role(role).label, "either"))
        for column in ctx.roles.get("battery", [])[:1]:
            out.risk_signals.append(trend_signal(ctx, column, "Battery", "down", max_score=1))

        if stuck_any:
            score = 2 if stuck_recent else 1
            out.risk_signals.append({
                "name": "Stuck readings", "column": None, "score": score, "weight": 1.0,
                "explanation": f"Repeated identical readings in {', '.join(stuck_any)}"
                               + (" during the most recent period." if stuck_recent else " (not recent)."),
            })
        gaps = ctx.trends.summary.get("gaps", []) if ctx.trends else []
        if gaps:
            recent_gap = recent_cutoff is not None and any(gap["end"] >= recent_cutoff for gap in gaps)
            out.risk_signals.append({
                "name": "Missing readings", "column": None, "score": 2 if recent_gap else 1, "weight": 1.0,
                "explanation": f"{len(gaps)} gap(s) in reporting" + (", including recently." if recent_gap else "."),
            })
        out.risk_signals = [signal for signal in out.risk_signals if signal]
        out.notes.append("Sensor-health signals describe data reliability and drift; they do not diagnose the "
                         "monitored equipment.")
        return out

    def _device_table(self, ctx, out, group) -> None:
        frame = ctx.frame
        rows = []
        gaps = ctx.trends.summary.get("gaps", []) if ctx.trends else []
        for name, part in frame.groupby(group, sort=True):
            row = [str(name), int(len(part))]
            if ctx.time_column:
                row += [str(part[ctx.time_column].min()), str(part[ctx.time_column].max())]
            row.append(sum(1 for gap in gaps if gap["series"] == str(name)))
            rows.append(row)
        columns = ["device", "readings"] + (["first", "last"] if ctx.time_column else []) + ["gaps"]
        out.tables.append({"title": "Readings per device", "columns": columns, "rows": rows[:20]})
        out.metrics.append({"label": "Devices", "value": int(frame[group].nunique()), "column": group})
