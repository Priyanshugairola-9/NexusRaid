"""Risk engine: a transparent, rule-based concern level for supported domains.

How the level is computed (all numbers are configurable):
  1. The domain analyzer produces signals, each scored 0-3:
       0 no concern, 1 mild, 2 elevated, 3 severe   (with a written reason)
  2. Two common signals are added when data allows:
       * recent anomaly concentration: more flagged rows lately than usual
       * co-movement: several 'stress' metrics worsening together
  3. Weighted score ratio = sum(weight x score) / sum(weight x 3)
       medium >= 0.2, high >= 0.4, critical >= 0.6
  4. Floors: any single severe signal -> at least High; two or more -> Critical.

The result is a concern indicator, not a probability of failure. Thresholds
are reasonable defaults, not calibrated against real incidents.
"""

from app.analyzers.checks import recent_vs_overall
from app.services.explanation import make_finding

LEVELS = ("Low", "Medium", "High", "Critical")
UNAVAILABLE_MESSAGE = "Risk assessment unavailable for this dataset."


def _unavailable(reason: str) -> dict:
    return {"available": False, "message": UNAVAILABLE_MESSAGE, "reason": reason}


def _anomaly_concentration(ctx) -> dict | None:
    stats = recent_vs_overall(ctx, ctx.anomalies.any_mask)
    if not stats or stats["overall_rate"] == 0:
        return None
    ratio, recent = stats["ratio"] or 0, stats["recent_rate"]
    if ratio >= 3 and recent >= 0.05:
        score = 2
    elif ratio >= 1.5 and recent >= 0.02:
        score = 1
    else:
        score = 0
    return {
        "name": "Recent anomaly concentration", "column": None, "score": score, "weight": 1.0,
        "explanation": f"{100 * recent:.1f}% of rows in the most recent 10% of the period were flagged, versus "
                       f"{100 * stats['overall_rate']:.1f}% overall ({ratio:.1f}x).",
    }


def _co_movement(ctx, analyzer) -> dict | None:
    worsening = []
    for role_name, columns in ctx.roles.items():
        direction = analyzer.role(role_name).direction
        for column in columns:
            state = ctx.trends.column_states.get(column) if ctx.trends else None
            if not state:
                continue
            if (direction == "higher_is_worse" and state["direction"] == "increasing") or (
                    direction == "lower_is_worse" and state["direction"] == "decreasing"):
                worsening.append(column)
    if len(worsening) < 2:
        return None
    return {
        "name": "Signals worsening together", "column": None, "score": 2 if len(worsening) >= 3 else 1,
        "weight": 1.0,
        "explanation": f"{', '.join(worsening)} are all moving in their 'worse' direction over the same period "
                       "(co-occurrence, not proof of a common cause).",
    }


def _level(ratio: float, signals: list[dict], cutoffs: dict) -> tuple[str, list[str]]:
    index = 0
    if ratio >= cutoffs["critical"]:
        index = 3
    elif ratio >= cutoffs["high"]:
        index = 2
    elif ratio >= cutoffs["medium"]:
        index = 1
    rules = [f"Weighted score ratio {ratio:.2f} -> {LEVELS[index]}."]
    severe = sum(1 for signal in signals if signal["score"] == 3)
    if severe >= 2 and index < 3:
        index = 3
        rules.append("Two or more severe signals raise the level to Critical.")
    elif severe == 1 and index < 2:
        index = 2
        rules.append("A severe signal raises the level to at least High.")
    return LEVELS[index], rules


def assess_risk(ctx, analyzer, domain: dict, domain_output) -> tuple[dict, list[dict]]:
    if domain["level"] == "none":
        return _unavailable("No supported domain was recognised, so there is no defensible basis for a risk "
                            "level. Anomalies are still reported."), []
    if not analyzer.risk_supported:
        return _unavailable(analyzer.risk_unsupported_reason), []
    if ctx.time_column is None:
        return _unavailable("Risk is judged from recent behaviour over time, which needs a date/time column."), []

    signals = list(domain_output.risk_signals if domain_output else [])
    for extra in (_anomaly_concentration(ctx), _co_movement(ctx, analyzer)):
        if extra:
            signals.append(extra)
    if not signals:
        return _unavailable("None of the domain's risk-relevant columns could be evaluated."), []

    total = sum(signal["weight"] * signal["score"] for signal in signals)
    maximum = sum(signal["weight"] * 3 for signal in signals)
    ratio = total / maximum if maximum else 0.0
    level, rules = _level(ratio, signals, ctx.config.risk_cutoffs)
    for signal in signals:
        signal["contribution"] = round(signal["weight"] * signal["score"] / total, 3) if total else 0.0
    ordered = sorted(signals, key=lambda signal: -signal["weight"] * signal["score"])
    top = [signal for signal in ordered if signal["score"] > 0][:3]

    risk = {
        "available": True,
        "title": getattr(analyzer, "risk_title", "Operational concern"),
        "level": level,
        "score_ratio": round(ratio, 3),
        "signals": ordered,
        "top_contributors": [signal["name"] for signal in top],
        "rules_applied": rules,
        "method": "Each signal is scored 0 (none) to 3 (severe) by documented rules and weighted. The level "
                  "follows from the weighted share of the maximum possible score, with floors for severe signals.",
        "cutoffs": ctx.config.risk_cutoffs,
        "disclaimer": "This is a rule-based concern indicator, not a probability of failure. Thresholds are "
                      "defaults that have not been calibrated against real incidents.",
    }
    findings = []
    if level in ("High", "Critical", "Medium"):
        findings.append(make_finding(
            source="risk", category="risk",
            severity="warning" if level in ("High", "Critical") else "notice",
            title=f"{risk['title']}: {level}",
            what_happened="Several risk-relevant signals are elevated. Main contributors: "
                          + (", ".join(risk["top_contributors"]) or "none") + ".",
            columns=sorted({signal["column"] for signal in top if signal["column"]}),
            observed="; ".join(f"{signal['name']}: {signal['score']}/3" for signal in top),
            comparison=f"Weighted score ratio {ratio:.2f} (medium >= {ctx.config.risk_cutoffs['medium']}, "
                       f"high >= {ctx.config.risk_cutoffs['high']}, critical >= {ctx.config.risk_cutoffs['critical']}).",
            why_flagged=" ".join(rules),
            method="Rule-based weighted scoring (see the Risk section)",
            could_indicate="Increasing operational stress or degradation that deserves attention.",
            confidence="medium",
            confidence_basis="Rules and thresholds are transparent defaults, not trained on incidents.",
            needs="Labelled incident history to calibrate thresholds for this system.",
            next_steps="Start with the top contributing signal and check its time-series chart.",
        ))
    return risk, findings
