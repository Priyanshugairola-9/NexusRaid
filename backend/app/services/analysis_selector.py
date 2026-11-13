"""Analysis selection: decide what runs on this dataset, and record why.

The plan is shown to the user so that nothing happens invisibly: which columns
are used as numeric inputs, which are excluded (and why), and which analysis
stages run or are skipped.
"""

from app.services.analysis_config import AnalysisConfig
from app.services.profiling import numeric_feature_columns

EXCLUSION_REASONS = {
    "identifier": "Identifier: unique per row, so arithmetic on it is meaningless.",
    "categorical": "Category labels: analysed by frequency and grouping, not arithmetic.",
    "boolean": "Yes/no column: analysed by frequency.",
    "datetime": "Date/time: used as the time axis, not as a measurement.",
    "text": "Free text: not analysed statistically.",
    "constant": "Only one distinct value: carries no information.",
    "empty": "No values.",
}


def build_plan(profile: dict, domain: dict, analyzer, config: AnalysisConfig) -> dict:
    features = numeric_feature_columns(profile["columns"])
    excluded = []
    for column in profile["columns"]:
        if column["name"] in features:
            continue
        if "label_candidate" in column["roles"]:
            reason = ("Looks like an outcome/label column. Using it as an input would leak the answer into "
                      "the analysis; it is only used to measure agreement afterwards, if possible.")
        elif column["kind"] == "numeric" and column["missing_pct"] >= 50:
            reason = f"{column['missing_pct']}% missing: too sparse to analyse reliably."
        else:
            reason = EXCLUSION_REASONS.get(column["kind"], "Not a numeric measurement.")
        excluded.append({"column": column["name"], "kind": column["kind"], "reason": reason})

    time_axis = profile["time_axis"]
    multivariate_runs = len(features) >= 2 and profile["overview"]["rows"] >= 50 and config.multivariate_method != "none"
    risk_ok = analyzer.risk_supported and domain["level"] != "none" and time_axis.get("kind") == "datetime"
    if domain["level"] == "none":
        risk_reason = "No supported domain was recognised."
    elif not analyzer.risk_supported:
        risk_reason = analyzer.risk_unsupported_reason
    elif time_axis.get("kind") != "datetime":
        risk_reason = "Risk is judged from recent behaviour, which needs a date/time column."
    else:
        risk_reason = "Supported for this domain; signals are listed with their scores."

    return {
        "features": features,
        "excluded_columns": excluded,
        "stages": [
            {"stage": "Profiling and cleaning", "runs": True, "reason": "Always runs."},
            {"stage": "Universal analysis", "runs": True, "reason": "Always runs."},
            {"stage": "Domain analysis", "runs": domain["level"] != "none",
             "reason": f"{domain['title']} ({domain['level']} evidence)." if domain["level"] != "none"
             else "No domain recognised."},
            {"stage": "Per-column anomaly detection", "runs": bool(features),
             "reason": f"{len(features)} numeric column(s); the method is chosen per column." if features
             else "No usable numeric columns."},
            {"stage": "Row-level anomaly detection", "runs": multivariate_runs,
             "reason": "Needs at least 2 numeric columns and 50 rows." if not multivariate_runs
             else f"Method setting: {config.multivariate_method}."},
            {"stage": "Trend and drift analysis", "runs": bool(time_axis.get("available")),
             "reason": time_axis.get("reason", "")},
            {"stage": "Risk assessment", "runs": risk_ok, "reason": risk_reason},
        ],
    }
