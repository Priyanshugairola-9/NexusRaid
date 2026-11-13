"""Base class for domain analyzers.

A domain analyzer declares the column ROLES it understands (e.g. "cpu",
"latency", "amount") with keywords used to recognise them. Domain detection
asks every analyzer how many of its roles the dataset's columns match.

To add a domain: create a subclass with `domain`, `title`, `roles` and an
`analyze()` method, then register it in registry.py. Nothing else changes.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.services.analysis_config import AnalysisConfig
from app.utils.data_utils import name_tokens


@dataclass(frozen=True)
class Role:
    name: str
    label: str
    keywords: tuple[str, ...]
    kinds: tuple[str, ...] = ("numeric",)
    core: bool = True
    # How a rising value should be read: "higher_is_worse", "lower_is_worse", "either" or "neutral".
    direction: str = "neutral"


@dataclass
class AnalysisContext:
    """Everything an analyzer may need, computed once by the pipeline."""
    frame: pd.DataFrame
    profile: dict
    config: AnalysisConfig
    features: list[str]
    roles: dict[str, list[str]]
    trends: object  # TrendResult
    anomalies: object  # AnomalyResult
    domain: str = "general"

    def column_profile(self, name: str) -> dict:
        return next(column for column in self.profile["columns"] if column["name"] == name)

    @property
    def time_column(self) -> str | None:
        axis = self.profile["time_axis"]
        return axis.get("column") if axis.get("available") and axis.get("kind") == "datetime" else None

    def first(self, role: str) -> str | None:
        columns = self.roles.get(role) or []
        return columns[0] if columns else None

    def numeric(self, column: str) -> np.ndarray:
        return self.frame[column].to_numpy(dtype=float)


@dataclass
class DomainOutput:
    findings: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    risk_signals: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def ran(self, name: str, detail: str = "") -> None:
        self.checks.append({"name": name, "status": "ran", "detail": detail})

    def skipped(self, name: str, reason: str) -> None:
        self.checks.append({"name": name, "status": "skipped", "detail": reason})


def _token_matches(token: str, part: str) -> bool:
    return token.startswith(part[:-1]) if part.endswith("*") else token == part


def keyword_score(tokens: list[str], keyword: str) -> int:
    """Number of words in `keyword` matched consecutively in `tokens` (0 = no match).

    "response time" matches ["avg", "response", "time", "ms"] with score 2;
    "temp*" matches "temperature" with score 1.
    """
    parts = keyword.split()
    for start in range(len(tokens) - len(parts) + 1):
        if all(_token_matches(tokens[start + offset], part) for offset, part in enumerate(parts)):
            return len(parts)
    return 0


class BaseAnalyzer:
    domain = "general"
    title = "General dataset"
    description = ""
    roles: tuple[Role, ...] = ()
    risk_supported = False
    risk_unsupported_reason = "No defensible operational risk model exists for this kind of data."

    def match_columns(self, columns: list[dict]) -> dict[str, list[str]]:
        """Assign each column to at most one of this analyzer's roles (most specific keyword wins)."""
        matches: dict[str, list[str]] = {}
        for column in columns:
            if column["kind"] in ("empty", "constant") or "label_candidate" in column["roles"]:
                continue
            tokens = name_tokens(column["name"])
            best: tuple[int, int, Role] | None = None
            for order, role in enumerate(self.roles):
                if column["kind"] not in role.kinds:
                    continue
                score = max((keyword_score(tokens, keyword) for keyword in role.keywords), default=0)
                if score and (best is None or (score, -order) > (best[0], -best[1])):
                    best = (score, order, role)
            if best:
                matches.setdefault(best[2].name, []).append(column["name"])
        return matches

    def role(self, name: str) -> Role:
        return next(role for role in self.roles if role.name == name)

    def analyze(self, ctx: AnalysisContext) -> DomainOutput:
        return DomainOutput()
