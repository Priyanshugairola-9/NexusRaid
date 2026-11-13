"""Universal analysis: checks that make sense for almost any table.

Runs on every dataset, recognised or not: duplicates, missing data, strong
relationships between numeric columns, and differences between groups.
"""

import numpy as np
from scipy.stats import kruskal

from app.analyzers.base_analyzer import AnalysisContext, BaseAnalyzer, DomainOutput
from app.services.explanation import make_finding
from app.utils.data_utils import format_number

MAX_COMPARE_NUMERIC = 8
MAX_COMPARE_GROUPS = 4
MIN_GROUP_SIZE = 5


class UniversalAnalyzer(BaseAnalyzer):
    domain = "general"
    title = "General dataset"
    description = "Statistical analysis that applies to any structured dataset."

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        out = DomainOutput()
        overview = ctx.profile["overview"]
        if overview["duplicate_rows"]:
            out.findings.append(make_finding(
                source="universal", category="data_quality",
                severity="warning" if overview["duplicate_pct"] >= 5 else "notice",
                title=f"{overview['duplicate_rows']:,} duplicate row(s)",
                what_happened="Some rows are exact copies of other rows.",
                columns=[], observed=f"{overview['duplicate_pct']}% of rows are duplicates.",
                comparison="Each real-world record normally appears once.",
                why_flagged="Duplicates inflate counts and can bias averages.",
                method="Exact row comparison",
                could_indicate="Repeated imports, retries in data collection, or genuinely identical events.",
                confidence="high", confidence_basis="Exact match on every column.",
                needs="Whether identical rows can legitimately occur in this data.",
                next_steps="Remove duplicates at the source if they are not legitimate. NexusRaid keeps them.",
            ))
        out.ran("Duplicate rows")

        high_missing = [c for c in ctx.profile["columns"] if 20 <= c["missing_pct"] < 100]
        if high_missing:
            out.findings.append(make_finding(
                source="universal", category="data_quality", severity="notice",
                title=f"{len(high_missing)} column(s) with at least 20% missing values",
                what_happened=", ".join(f"{c['name']} ({c['missing_pct']}%)" for c in high_missing[:8]) + ".",
                columns=[c["name"] for c in high_missing],
                observed="Missing values are counted per column.",
                comparison="Less than about 5% missing is usually harmless for summary statistics.",
                why_flagged="Large gaps can make statistics unrepresentative.",
                method="Missing-value count",
                could_indicate="Optional fields, collection problems, or data merged from different sources.",
                confidence="high", confidence_basis="Direct count.",
                needs="Why values are missing (randomly or for a reason).",
                next_steps="Interpret results for these columns with care.",
            ))
        out.ran("Missing values")

        correlations = ctx.profile.get("correlations", {})
        pairs = correlations.get("strong_pairs") or []
        if pairs:
            out.findings.append(make_finding(
                source="universal", category="relationship", severity="info",
                title=f"{len(pairs)} strongly related column pair(s)",
                what_happened="; ".join(f"{p['a']} and {p['b']} (rho {p['rho']})" for p in pairs[:5]) + ".",
                columns=sorted({p["a"] for p in pairs[:5]} | {p["b"] for p in pairs[:5]}),
                observed=f"{len(pairs)} pair(s) with |rho| >= 0.7.",
                comparison="Spearman rho: 0 = unrelated, ±1 = perfectly monotonic.",
                why_flagged="Strong relationships help explain the data and can reveal redundant columns.",
                method="Spearman rank correlation",
                could_indicate="A shared cause, one column derived from another, or a real dependency. "
                               "Correlation alone does not show cause and effect.",
                confidence="high" if ctx.profile["overview"]["rows"] >= 100 else "medium",
                confidence_basis=f"Computed over {ctx.profile['overview']['rows']:,} rows.",
                needs="Domain knowledge about how the columns are produced.",
                next_steps="See the correlation matrix on the Dataset Profile page.",
            ))
        out.ran("Relationships between numeric columns")
        self._group_differences(ctx, out)
        return out

    def _group_differences(self, ctx: AnalysisContext, out: DomainOutput) -> None:
        groups = [
            c["name"] for c in ctx.profile["columns"]
            if c["kind"] == "categorical" and 2 <= c["unique"] <= 10 and "label_candidate" not in c["roles"]
        ][:MAX_COMPARE_GROUPS]
        numeric = ctx.features[:MAX_COMPARE_NUMERIC]
        if not groups or not numeric:
            out.skipped("Differences between groups", "Needs a categorical column with 2-10 groups and a numeric column.")
            return
        out.ran("Differences between groups", "Kruskal-Wallis test, reported when p < 0.001 and effect is at least medium")
        rows = []
        for group in groups:
            for column in numeric:
                data = ctx.frame[[group, column]].dropna()
                samples = [part[column].to_numpy(dtype=float) for _, part in data.groupby(group)
                           if len(part) >= MIN_GROUP_SIZE]
                if len(samples) < 2 or all(np.ptp(sample) == 0 for sample in samples):
                    continue
                statistic, p_value = kruskal(*samples)
                n, k = sum(len(sample) for sample in samples), len(samples)
                effect = (statistic - k + 1) / (n - k) if n > k else 0.0
                if p_value < 0.001 and effect >= 0.06:
                    medians = data.groupby(group)[column].median().sort_values()
                    rows.append([column, group, round(effect, 3),
                                 f"{medians.index[0]}: {format_number(medians.iloc[0])}",
                                 f"{medians.index[-1]}: {format_number(medians.iloc[-1])}"])
        if rows:
            out.tables.append({"title": "Numeric columns that differ between groups",
                               "columns": ["column", "grouped by", "effect size", "lowest median", "highest median"],
                               "rows": rows})
            out.findings.append(make_finding(
                source="universal", category="relationship", severity="info",
                title=f"{len(rows)} numeric column(s) differ clearly between groups",
                what_happened="; ".join(f"{row[0]} by {row[1]}" for row in rows[:5]) + ".",
                columns=sorted({row[0] for row in rows} | {row[1] for row in rows}),
                observed="See the 'Numeric columns that differ between groups' table.",
                comparison="Effect size (epsilon squared): 0.01 small, 0.06 medium, 0.14 large.",
                why_flagged="Group differences are often the first thing worth understanding in a dataset.",
                method="Kruskal-Wallis H test (no normality assumption)",
                could_indicate="The groups genuinely behave differently. The test does not explain why.",
                confidence="medium", confidence_basis="Statistical test on this dataset only.",
                needs="Whether the groups are comparable in other respects.",
                next_steps="Compare the groups' distributions in the column inspector.",
            ))
