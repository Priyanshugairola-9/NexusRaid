"""The analysis pipeline: runs every stage in order and assembles the result.

  profile (already done at upload) -> domain detection -> analysis plan
  -> anomaly detection -> trend analysis -> universal + domain analyzers
  -> risk assessment -> findings + summary

The pipeline only uses pandas/numpy/scikit-learn, so it can be tested and
reused (for example by live monitoring) without the web framework.
"""

import time
from dataclasses import dataclass

import pandas as pd

from app.analyzers.base_analyzer import AnalysisContext, DomainOutput
from app.analyzers.registry import UNIVERSAL_ANALYZER, get_analyzer
from app.services.analysis_config import AnalysisConfig
from app.services.analysis_selector import build_plan
from app.services.anomaly_detection import detect_anomalies
from app.services.domain_detection import detect_domain
from app.services.explanation import build_summary, renumber
from app.services.risk_engine import assess_risk
from app.services.trend_analysis import analyze_trends
from app.utils.data_utils import to_jsonable


@dataclass
class AnalysisOutcome:
    results: dict
    records: list[dict]


def _panel(analyzer, output: DomainOutput | None) -> dict:
    if output is None:
        return {"available": False}
    return {
        "available": True,
        "domain": analyzer.domain,
        "title": analyzer.title,
        "checks": output.checks,
        "metrics": output.metrics,
        "tables": output.tables,
        "notes": output.notes,
    }


def run_analysis(profile: dict, frame: pd.DataFrame, config: AnalysisConfig | None = None) -> AnalysisOutcome:
    config = config or AnalysisConfig()
    timings = {}

    def timed(name, function, *args, **kwargs):
        started = time.perf_counter()
        result = function(*args, **kwargs)
        timings[name] = round(time.perf_counter() - started, 3)
        return result

    domain = timed("domain_detection", detect_domain, profile, frame)
    analyzer = get_analyzer(domain["detected"])
    plan = build_plan(profile, domain, analyzer, config)
    features = plan["features"]
    time_axis = profile["time_axis"]
    time_column = time_axis.get("column") if time_axis.get("available") else None

    anomalies = timed("anomaly_detection", detect_anomalies, frame, profile, features, config, time_column)
    trends = timed("trend_analysis", analyze_trends, frame, profile, features, config, anomalies.column_masks)

    context = AnalysisContext(
        frame=frame, profile=profile, config=config, features=features,
        roles=domain["matched_roles"], trends=trends, anomalies=anomalies, domain=analyzer.domain,
    )
    universal_output = timed("universal_analysis", UNIVERSAL_ANALYZER.analyze, context)
    domain_output = None
    if analyzer is not UNIVERSAL_ANALYZER:
        domain_output = timed("domain_analysis", analyzer.analyze, context)
    risk, risk_findings = timed("risk_assessment", assess_risk, context, analyzer, domain, domain_output)

    findings = renumber(
        anomalies.findings + trends.findings + universal_output.findings
        + (domain_output.findings if domain_output else []) + risk_findings
    )
    summary = build_summary(domain, anomalies.summary, trends.summary, risk, findings)
    results = {
        "meta": {"timings_seconds": timings, "total_seconds": round(sum(timings.values()), 3),
                 "rows": profile["overview"]["rows"], "columns": profile["overview"]["columns"]},
        "config": config.to_dict(),
        "summary": summary,
        "domain": domain,
        "plan": plan,
        "anomalies": anomalies.summary,
        "trends": trends.summary,
        "universal": _panel(UNIVERSAL_ANALYZER, universal_output),
        "domain_analysis": _panel(analyzer, domain_output),
        "risk": risk,
        "findings": findings,
    }
    return AnalysisOutcome(results=to_jsonable(results), records=anomalies.records)
