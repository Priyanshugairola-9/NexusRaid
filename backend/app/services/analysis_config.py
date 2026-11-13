"""Every tunable number used by the analysis, in one place.

Defaults are reasonable starting points, NOT values calibrated against real
incidents. They can be changed from the Settings page or per analysis run.
"""

from dataclasses import asdict, dataclass, field, fields

UNIVARIATE_METHODS = ("auto", "zscore", "modified_zscore", "iqr")
MULTIVARIATE_METHODS = ("auto", "isolation_forest", "lof", "dbscan", "none")


def _default_risk_thresholds() -> dict:
    # Percent-of-capacity levels for utilisation metrics: (warning, critical).
    return {"cpu": [80.0, 95.0], "memory": [85.0, 95.0], "disk": [85.0, 95.0], "error_rate_pct": [1.0, 5.0]}


def _default_risk_cutoffs() -> dict:
    # Share of the maximum possible weighted score needed for each level.
    return {"medium": 0.2, "high": 0.4, "critical": 0.6}


@dataclass
class AnalysisConfig:
    # Univariate (one column at a time)
    univariate_method: str = "auto"
    zscore_threshold: float = 3.0
    modified_zscore_threshold: float = 3.5
    iqr_multiplier: float = 3.0

    # Multivariate (whole rows)
    multivariate_method: str = "auto"
    multivariate_threshold: float = 6.0
    lof_neighbors: int = 20
    dbscan_min_samples: int = 10

    # Trends and changes over time
    trend_p_value: float = 0.001
    trend_min_tau: float = 0.3
    drift_threshold: float = 3.0
    spike_threshold: float = 6.0
    shift_threshold: float = 6.0

    # Risk engine
    risk_thresholds: dict = field(default_factory=_default_risk_thresholds)
    risk_cutoffs: dict = field(default_factory=_default_risk_cutoffs)

    random_seed: int = 42

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "AnalysisConfig":
        """Build a config from user input, rejecting unknown or out-of-range values."""
        config = cls()
        if not values:
            return config
        known = {item.name for item in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
        for key, value in values.items():
            if value is None:
                continue
            if key in ("risk_thresholds", "risk_cutoffs"):
                merged = dict(getattr(config, key))
                merged.update(value)
                setattr(config, key, merged)
            else:
                setattr(config, key, value)
        config.validate()
        return config

    def validate(self) -> None:
        def check(condition: bool, message: str) -> None:
            if not condition:
                raise ValueError(message)

        check(self.univariate_method in UNIVARIATE_METHODS, f"univariate_method must be one of {UNIVARIATE_METHODS}")
        check(self.multivariate_method in MULTIVARIATE_METHODS,
              f"multivariate_method must be one of {MULTIVARIATE_METHODS}")
        check(1.5 <= self.zscore_threshold <= 10, "zscore_threshold must be between 1.5 and 10")
        check(1.5 <= self.modified_zscore_threshold <= 10, "modified_zscore_threshold must be between 1.5 and 10")
        check(0.5 <= self.iqr_multiplier <= 10, "iqr_multiplier must be between 0.5 and 10")
        check(2 <= self.multivariate_threshold <= 10, "multivariate_threshold must be between 2 and 10")
        check(5 <= int(self.lof_neighbors) <= 100, "lof_neighbors must be between 5 and 100")
        check(3 <= int(self.dbscan_min_samples) <= 100, "dbscan_min_samples must be between 3 and 100")
        check(0 < self.trend_p_value <= 0.05, "trend_p_value must be between 0 and 0.05")
        check(0.05 <= self.trend_min_tau <= 0.9, "trend_min_tau must be between 0.05 and 0.9")
        check(1 <= self.drift_threshold <= 20, "drift_threshold must be between 1 and 20")
        check(2 <= self.spike_threshold <= 20, "spike_threshold must be between 2 and 20")
        check(2 <= self.shift_threshold <= 20, "shift_threshold must be between 2 and 20")
        for name, pair in self.risk_thresholds.items():
            check(isinstance(pair, (list, tuple)) and len(pair) == 2 and 0 <= pair[0] < pair[1],
                  f"risk_thresholds.{name} must be [warning, critical] with warning < critical")
        cutoffs = self.risk_cutoffs
        check(set(cutoffs) == {"medium", "high", "critical"}, "risk_cutoffs needs medium, high and critical")
        check(0 < cutoffs["medium"] < cutoffs["high"] < cutoffs["critical"] <= 1,
              "risk_cutoffs must satisfy 0 < medium < high < critical <= 1")
        self.lof_neighbors = int(self.lof_neighbors)
        self.dbscan_min_samples = int(self.dbscan_min_samples)
