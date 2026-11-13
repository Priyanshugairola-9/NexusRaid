"""Explainability engine: turns detections into findings a person can act on.

Every finding answers the same questions:
  what happened? which columns? what value? compared with what normal range?
  why was it flagged? which method? what could it indicate? how confident?
  what extra information is needed? what should be investigated next?

Explanations are produced by transparent rules (templates filled with real
numbers), not by a language model, so they work offline and can be audited.
Confidence is rule-based ("high" means strong statistical evidence by the
rules documented in docs/ALGORITHMS.md), never a probability.
"""

from itertools import count

SEVERITY_ORDER = {"warning": 0, "notice": 1, "info": 2}
CONFIDENCE_LEVELS = ("low", "medium", "high")

_ids = count(1)


def make_finding(
    *,
    source: str,
    category: str,
    title: str,
    what_happened: str,
    columns: list[str],
    observed: str,
    comparison: str,
    why_flagged: str,
    method: str,
    could_indicate: str,
    confidence: str,
    confidence_basis: str,
    needs: str,
    next_steps: str,
    severity: str = "notice",
    evidence: dict | None = None,
) -> dict:
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}")
    if severity not in SEVERITY_ORDER:
        raise ValueError(f"severity must be one of {tuple(SEVERITY_ORDER)}")
    return {
        "id": f"F{next(_ids)}",
        "source": source,
        "category": category,
        "severity": severity,
        "title": title,
        "what_happened": what_happened,
        "columns": columns,
        "observed": observed,
        "comparison": comparison,
        "why_flagged": why_flagged,
        "method": method,
        "could_indicate": could_indicate,
        "confidence": {"level": confidence, "basis": confidence_basis},
        "needs": needs,
        "next_steps": next_steps,
        "evidence": evidence or {},
    }


def renumber(findings: list[dict]) -> list[dict]:
    """Sort findings (most important first) and give them stable ids F1, F2, ..."""
    ordered = sorted(
        findings,
        key=lambda finding: (
            SEVERITY_ORDER[finding["severity"]],
            -CONFIDENCE_LEVELS.index(finding["confidence"]["level"]),
        ),
    )
    for number, finding in enumerate(ordered, start=1):
        finding["id"] = f"F{number}"
    return ordered


def build_summary(domain: dict, anomalies: dict, trends: dict, risk: dict, findings: list[dict]) -> dict:
    """A short, plain-language overview shown at the top of the results page."""
    lines = []
    if domain["detected"] == "general":
        lines.append("The dataset did not match a known domain, so general statistical analysis was used.")
    else:
        lines.append(
            f"The dataset looks like {domain['title']} data ({domain['level']} evidence); "
            f"{'all' if domain['level'] == 'strong' else 'the supported'} domain checks were run."
        )
    total_flagged = anomalies.get("flagged_rows", 0)
    if anomalies.get("observations"):
        lines.append(
            f"{total_flagged:,} of {anomalies['observations']:,} rows "
            f"({anomalies.get('flagged_pct', 0):.2f}%) were flagged as statistically unusual by at least one method."
        )
    if trends.get("available"):
        changing = [item["column"] for item in trends.get("trend_summary", []) if item["direction"] != "stable"]
        if changing:
            unique = list(dict.fromkeys(changing))
            lines.append(f"Clear trends over time: {', '.join(unique[:6])}{' and more' if len(unique) > 6 else ''}.")
        else:
            lines.append("No clear upward or downward trends were found over time.")
    else:
        lines.append("Trend analysis was skipped: " + trends.get("reason", "no time axis."))
    if risk.get("available"):
        lines.append(f"Operational concern level: {risk['level']} (rule-based indicator, not a failure probability).")
    else:
        lines.append("Risk assessment unavailable for this dataset.")

    warnings = sum(1 for finding in findings if finding["severity"] == "warning")
    return {
        "headline": lines[0],
        "lines": lines,
        "finding_counts": {
            "total": len(findings),
            "warning": warnings,
            "notice": sum(1 for finding in findings if finding["severity"] == "notice"),
            "info": sum(1 for finding in findings if finding["severity"] == "info"),
        },
        "reminder": "Unusual does not mean harmful. Every finding is a lead to investigate, not a confirmed incident.",
    }
