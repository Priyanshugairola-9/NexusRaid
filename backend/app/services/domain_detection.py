"""Domain detection: what kind of dataset is this?

Rule-based by design. Each domain analyzer lists column roles ("cpu",
"amount", "temperature") and keywords. The domain whose roles are matched
best wins. Evidence is reported as a LEVEL, not a percentage, because counting
keyword matches cannot honestly produce a probability:

  strong   at least two of the domain's core roles are present -> full domain analysis
  partial  one core role, or two supporting roles               -> only the checks the columns support
  none     nothing matched                                      -> universal analysis only

Detection reads column names and types. It cannot verify what a column
really measures; a mislabelled column will mislead it.
"""

import numpy as np
import pandas as pd

from app.analyzers.registry import DOMAIN_ANALYZERS

LEVEL_RANK = {"strong": 2, "partial": 1, "none": 0}
PERCENT_ROLES = {"cpu", "memory", "disk", "humidity", "attendance"}


def _evaluate(analyzer, columns: list[dict]) -> dict:
    matches = analyzer.match_columns(columns)
    core = [name for name in matches if analyzer.role(name).core]
    supporting = [name for name in matches if not analyzer.role(name).core]
    if len(core) >= 2:
        level = "strong"
    elif len(core) == 1 or len(supporting) >= 2:
        level = "partial"
    else:
        level = "none"
    reasons = []
    for role_name, column_names in matches.items():
        role = analyzer.role(role_name)
        kind = "core" if role.core else "supporting"
        reasons.append(f"{', '.join(repr(name) for name in column_names)} matched {role.label} ({kind} signal).")
    missing_core = [role.label for role in analyzer.roles if role.core and role.name not in matches]
    return {
        "domain": analyzer.domain,
        "title": analyzer.title,
        "level": level,
        "core_matched": len(core),
        "supporting_matched": len(supporting),
        "matched_roles": matches,
        "reasons": reasons,
        "missing_core_roles": missing_core,
        "_rank": (LEVEL_RANK[level], 2 * len(core) + len(supporting)),
    }


def _plausibility_notes(frame: pd.DataFrame | None, matched: dict[str, list[str]]) -> list[str]:
    notes = []
    if frame is None:
        return notes
    for role, names in matched.items():
        if role not in PERCENT_ROLES:
            continue
        for name in names:
            values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size and (values.max() > 100 or values.min() < 0):
                notes.append(f"'{name}' has values outside 0-100, so it may not be a percentage as its name suggests.")
    return notes


def detect_domain(profile: dict, frame: pd.DataFrame | None = None) -> dict:
    columns = profile["columns"]
    candidates = sorted((_evaluate(analyzer, columns) for analyzer in DOMAIN_ANALYZERS),
                        key=lambda item: item["_rank"], reverse=True)
    best = candidates[0]
    alternatives = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in candidates[1:] if item["level"] != "none"
    ]
    limitations = [
        "Detection is based on column names and data types; it does not verify what the values mean.",
    ]

    if best["level"] == "none":
        return {
            "detected": "general",
            "title": "General dataset",
            "level": "none",
            "outcome": "unknown",
            "matched_roles": {},
            "relevant_columns": [],
            "reasons": ["No column names matched the vocabulary of any supported domain."],
            "missing_core_roles": [],
            "alternatives": [],
            "ambiguous": False,
            "limitations": limitations + ["Universal statistical analysis is used instead of domain checks."],
        }

    runner_up = candidates[1] if len(candidates) > 1 else None
    ambiguous = bool(runner_up and runner_up["_rank"] == best["_rank"])
    if ambiguous:
        limitations.append(
            f"{best['title']} and {runner_up['title']} match equally well; {best['title']} was chosen by "
            "list order. Treat the domain-specific results with extra care."
        )
    if best["level"] == "partial":
        limitations.append(
            "Only part of the domain's expected columns were found, so only the checks those columns support "
            f"are run. Missing core signals: {', '.join(best['missing_core_roles']) or 'none'}."
        )
    limitations += _plausibility_notes(frame, best["matched_roles"])
    relevant = sorted({name for names in best["matched_roles"].values() for name in names})
    return {
        "detected": best["domain"],
        "title": best["title"],
        "level": best["level"],
        "outcome": "recognized" if best["level"] == "strong" else "partial",
        "core_matched": best["core_matched"],
        "supporting_matched": best["supporting_matched"],
        "matched_roles": best["matched_roles"],
        "relevant_columns": relevant,
        "reasons": best["reasons"],
        "missing_core_roles": best["missing_core_roles"],
        "alternatives": alternatives,
        "ambiguous": ambiguous,
        "limitations": limitations,
    }
