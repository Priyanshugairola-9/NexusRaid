"""Network traffic: volumes, connections, sources, destinations, ports, protocols."""

import numpy as np

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput, Role
from app.analyzers.checks import distribution_table, event_bursts, percentile_metrics
from app.services.explanation import make_finding

CATEGORY_KINDS = ("categorical", "identifier", "text")


class NetworkAnalyzer(BaseAnalyzer):
    domain = "network"
    title = "Network traffic"
    description = "Network flows or connections: who talks to whom, how much, and when."
    risk_supported = False
    risk_unsupported_reason = ("Unusual traffic is not evidence of an attack or failure, and no validated "
                               "risk model exists for traffic records, so no risk level is assigned.")
    roles = (
        Role("bytes", "Traffic volume", ("bytes*", "octets", "bandwidth", "throughput", "traffic", "data volume")),
        Role("packets", "Packets", ("packet*", "pkts", "pkt*")),
        Role("source", "Source", ("src", "source", "src ip", "source ip", "client ip", "client"), kinds=CATEGORY_KINDS),
        Role("destination", "Destination", ("dst", "dest*", "destination", "server ip", "target ip"),
             kinds=CATEGORY_KINDS),
        Role("port", "Port", ("port", "dst port", "src port", "dest port", "destination port", "source port"),
             kinds=("categorical", "numeric")),
        Role("protocol", "Protocol", ("protocol", "proto"), kinds=("categorical",)),
        Role("connections", "Connections", ("connection*", "conn*", "flows", "sessions")),
        Role("duration", "Duration", ("duration", "elapsed"), core=False),
    )

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        source = ctx.first("source")
        if source:
            share = distribution_table(ctx, out, source, "Most active sources")
            self._concentration(ctx, out, source, share)
            event_bursts(ctx, out, source, "1min", "source", "connections")
        else:
            out.skipped("Bursts per source", "No source column found.")
        for role, title in (("destination", "Most contacted destinations"), ("protocol", "Protocols"),
                            ("port", "Most used ports")):
            column = ctx.first(role)
            if column:
                distribution_table(ctx, out, column, title)
        port = ctx.first("port")
        if port:
            out.metrics.append({"label": "Distinct ports", "value": int(ctx.frame[port].nunique()), "column": port})
        for column in ctx.roles.get("bytes", [])[:2]:
            percentile_metrics(ctx, out, column, column)
            flagged = ctx.anomalies.summary.get("column_flag_counts", {}).get(column, 0)
            out.metrics.append({"label": f"Unusually large/small {column}", "value": flagged, "column": column})
        out.notes.append("NexusRaid does not classify traffic as attacks. Flags are unusual patterns to review "
                         "with network context.")
        return out

    def _concentration(self, ctx, out, column, share) -> None:
        if share["distinct"] < 5 or not share["second_share"] or share["top_share"] < 3 * share["second_share"]:
            return
        out.findings.append(make_finding(
            source=self.domain, category="pattern", severity="info",
            title=f"{share['top']} accounts for {share['top_share']:.1f}% of all rows",
            what_happened=f"One {column} value is much more active than any other.",
            columns=[column],
            observed=f"Top: {share['top_share']:.1f}% of rows; next: {share['second_share']:.1f}%.",
            comparison=f"{share['distinct']} distinct values in total.",
            why_flagged="Activity that is concentrated on one source stands out from an otherwise even spread.",
            method="Frequency analysis",
            could_indicate="A server, scanner, backup job, misconfigured client or simply a busy host.",
            confidence="high", confidence_basis="Direct count.",
            needs="An inventory of what that host is supposed to do.",
            next_steps="Review that source's connections over time.",
        ))
