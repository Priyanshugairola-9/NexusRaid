"""Server monitoring: CPU, memory, disk, I/O, network, response time, errors."""

import numpy as np

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import (
    bounds_check, is_percent_like, latency_level_signal, level_signal, linear_projection, percentile_metrics,
    sustained_high, trend_signal,
)
from app.utils.data_utils import round_or_none

UTILISATION_ROLES = (("cpu", "CPU"), ("memory", "Memory"), ("disk", "Disk"))


class ServerAnalyzer(BaseAnalyzer):
    domain = "server"
    title = "Server monitoring"
    description = "Resource utilisation and performance metrics of a computer or server."
    risk_supported = True
    risk_title = "Operational stress"
    roles = (
        Role("cpu", "CPU usage", ("cpu", "cpu*", "processor"), direction="higher_is_worse"),
        Role("memory", "Memory usage", ("memory", "mem", "ram", "swap"), direction="higher_is_worse"),
        Role("disk", "Disk usage", ("disk", "storage", "filesystem", "fs", "volume"), direction="higher_is_worse"),
        Role("disk_io", "Disk I/O", ("disk read", "disk write", "read bytes", "write bytes", "iops", "io",
                                     "read mb", "write mb", "disk io"), core=False),
        Role("network", "Network traffic", ("network", "net", "rx", "tx", "bandwidth"), core=False),
        Role("load", "System load", ("load", "load avg*"), core=False, direction="higher_is_worse"),
        Role("response_time", "Response time", ("response time", "latency", "resp time"), core=False,
             direction="higher_is_worse"),
        Role("errors", "Errors", ("error*", "fail*", "exception*", "err"), core=False, direction="higher_is_worse"),
        Role("processes", "Processes", ("process*", "threads", "proc"), core=False),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        thresholds = ctx.config.risk_thresholds
        for role, label in UTILISATION_ROLES:
            for position, column in enumerate(ctx.roles.get(role, [])[:2]):
                # Only the first column of each role feeds the risk score (no double counting).
                use_for_risk = position == 0
                values = ctx.numeric(column)
                finite = values[np.isfinite(values)]
                mostly_percent = finite.size and np.mean((finite >= 0) & (finite <= 100)) >= 0.9 and finite.max() > 1
                if not mostly_percent:
                    out.notes.append(f"{column} does not look like a percentage, so % thresholds are not applied.")
                    if use_for_risk:
                        out.risk_signals.append(trend_signal(ctx, column, label, "up"))
                    continue
                if not is_percent_like(ctx, column):
                    bounds_check(ctx, out, column, 0, 100, "percentage")
                warning, critical = thresholds.get(role, [80, 95])
                state = sustained_high(ctx, out, column, warning, critical, label)
                if use_for_risk:
                    out.risk_signals.append(level_signal(state, label))
                    out.risk_signals.append(trend_signal(ctx, column, label, "up"))
                out.metrics.append({"label": f"{label} median", "column": column,
                                    "value": round_or_none(np.median(finite), 2)})
                if role == "disk":
                    linear_projection(ctx, out, column, 100, "Disk usage")

        response = ctx.first("response_time")
        if response:
            percentile_metrics(ctx, out, response, "Response time")
            out.risk_signals.append(trend_signal(ctx, response, "Response time", "up"))
            out.risk_signals.append(latency_level_signal(ctx, response, "Response time"))
        if ctx.first("errors"):
            out.risk_signals.append(trend_signal(ctx, ctx.first("errors"), "Errors", "up"))
        if ctx.roles.get("load"):
            out.risk_signals.append(trend_signal(ctx, ctx.roles["load"][0], "System load", "up"))

        out.risk_signals = [signal for signal in out.risk_signals if signal]
        out.notes.append("Historical metrics can show stress and degradation, but they cannot prove that a "
                         "server failed or will fail.")
        return out
