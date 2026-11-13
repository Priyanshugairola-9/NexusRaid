"""Website / web-service performance: traffic, latency, errors, status codes."""

import numpy as np
import pandas as pd

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import (
    distribution_table, latency_level_signal, level_signal, percentile_metrics, trend_signal,
)
from app.services.explanation import make_finding
from app.utils.data_utils import format_number, round_or_none


class WebsiteAnalyzer(BaseAnalyzer):
    domain = "website"
    title = "Website performance"
    description = "Request volume, latency and error metrics of a website or web API."
    risk_supported = True
    risk_title = "Service degradation"
    roles = (
        Role("requests", "Request volume", ("request*", "hits", "rps", "qps", "pageviews", "page views", "visits",
                                            "throughput")),
        Role("latency", "Latency", ("response time", "latency", "ttfb", "load time", "duration", "resp time",
                                    "p50", "p95", "p99"), direction="higher_is_worse"),
        Role("errors", "Errors", ("error*", "5xx", "4xx", "fail*", "err"), direction="higher_is_worse"),
        Role("status", "HTTP status", ("status", "status code", "http status"), kinds=("categorical",)),
        Role("endpoint", "Endpoint", ("endpoint", "url", "path", "page", "route", "uri"),
             kinds=("categorical", "text", "identifier"), core=False),
        Role("users", "Users / sessions", ("user*", "session*", "visitor*"), core=False),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        latency_columns = ctx.roles.get("latency", [])[:2]
        for column in latency_columns:
            percentile_metrics(ctx, out, column, column)
        if latency_columns:
            # avg and p95 latency describe the same thing; only the first feeds the risk score.
            out.risk_signals.append(trend_signal(ctx, latency_columns[0], "Latency", "up", weight=1.5))
            out.risk_signals.append(latency_level_signal(ctx, latency_columns[0], "Latency", weight=1.5))

        errors, requests = ctx.first("errors"), ctx.first("requests")
        if errors and requests:
            self._error_rate(ctx, out, errors, requests)
        elif errors:
            out.risk_signals.append(trend_signal(ctx, errors, "Errors", "up", weight=1.5))
            out.skipped("Error rate", "Needs both an error count and a request count column.")
        else:
            out.skipped("Error rate", "No error column found.")

        status = ctx.first("status")
        if status:
            codes = pd.to_numeric(ctx.frame[status], errors="coerce")
            if codes.notna().mean() > 0.9:
                share = 100 * (codes >= 500).mean()
                out.metrics.append({"label": "Responses with 5xx status", "value": round(share, 2), "column": status,
                                    "unit": "%"})
            distribution_table(ctx, out, status, "Status codes")

        if requests:
            values = ctx.numeric(requests)
            out.metrics.append({"label": "Median requests per row", "column": requests,
                                "value": round_or_none(np.nanmedian(values), 1)})
            if latency_columns:
                self._load_sensitivity(ctx, out, requests, latency_columns[0])
        endpoint = ctx.first("endpoint")
        if endpoint:
            distribution_table(ctx, out, endpoint, "Most frequent endpoints")
        out.risk_signals = [signal for signal in out.risk_signals if signal]
        return out

    def _error_rate(self, ctx, out, errors, requests) -> None:
        err = ctx.numeric(errors)
        req = ctx.numeric(requests)
        valid = np.isfinite(err) & np.isfinite(req) & (req > 0)
        if valid.sum() < 10:
            out.skipped("Error rate", "Too few rows with both errors and requests.")
            return
        overall = 100 * err[valid].sum() / req[valid].sum()
        rate = np.where(valid, 100 * err / np.where(req > 0, req, np.nan), np.nan)
        out.metrics.append({"label": "Error rate (whole period)", "value": round(overall, 3), "unit": "%",
                            "column": errors})
        warning, critical = ctx.config.risk_thresholds.get("error_rate_pct", [1.0, 5.0])
        if ctx.time_column:
            times = ctx.frame[ctx.time_column]
            cutoff = times.min() + 0.9 * (times.max() - times.min())
            mask = (times >= cutoff).to_numpy() & valid
            recent_rate = 100 * err[mask].sum() / req[mask].sum() if req[mask].sum() else overall
        else:
            recent_rate = overall
        out.metrics.append({"label": "Error rate (most recent 10%)", "value": round(recent_rate, 3), "unit": "%",
                            "column": errors})
        out.ran("Error rate", f"warning {warning:g}%, critical {critical:g}%")
        state = {"column": errors, "recent_median": recent_rate, "warning": warning, "critical": critical}
        out.risk_signals.append(level_signal(state, "Error rate", weight=1.5, near_band=warning / 2))
        out.risk_signals.append(trend_signal(ctx, errors, "Errors", "up"))
        peak_index = int(np.nanargmax(rate))
        if np.nanmax(rate) >= warning:
            peak_rows = int(np.sum(rate >= warning))
            out.findings.append(make_finding(
                source=self.domain, category="pattern",
                severity="warning" if recent_rate >= warning else "notice",
                title=f"Error rate reached {np.nanmax(rate):.1f}% ({peak_rows} row(s) above {warning:g}%)",
                what_happened=f"The share of failed requests ({errors} / {requests}) exceeded the warning level in "
                              f"{peak_rows} row(s).",
                columns=[errors, requests],
                observed=f"Peak {np.nanmax(rate):.2f}% at data row {peak_index + 1}; recent {recent_rate:.2f}%.",
                comparison=f"Whole-period error rate {overall:.2f}%; warning level {warning:g}%.",
                why_flagged="Error rate (not raw error count) is used so that busy periods are not mistaken for "
                            "failures.",
                method="Ratio of errors to requests",
                could_indicate="A failing dependency, a bad deployment, or overload.",
                confidence="high", confidence_basis="Directly computed from the data.",
                needs="Deployment and incident history for the affected period.",
                next_steps="Find the start time of the elevated error rate and compare it with change logs.",
            ))

    def _load_sensitivity(self, ctx, out, requests, latency) -> None:
        pair = ctx.frame[[requests, latency]].astype(float).dropna()
        if len(pair) < 30:
            return
        rho = pair.corr(method="spearman").iloc[0, 1]
        out.ran("Latency versus traffic", f"Spearman rho = {rho:.2f}")
        if np.isfinite(rho) and rho >= 0.5:
            out.findings.append(make_finding(
                source=self.domain, category="relationship", severity="info",
                title=f"{latency} rises with {requests} (rho {rho:.2f})",
                what_happened="Latency tends to be higher when traffic is higher.",
                columns=[requests, latency],
                observed=f"Spearman correlation {rho:.2f} over {len(pair):,} rows.",
                comparison="0 = no relationship, 1 = perfectly increasing together.",
                why_flagged="Load-sensitive latency suggests limited headroom.",
                method="Spearman rank correlation",
                could_indicate="The service slows down under load (capacity limit). Correlation is not proof.",
                confidence="medium", confidence_basis="Correlation over the observed period only.",
                needs="Load tests or capacity information.",
                next_steps="Look at latency at peak traffic times.",
            ))
