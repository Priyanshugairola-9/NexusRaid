"""The list of available analyzers. Add a new domain here after creating its class."""

from app.analyzers.base_analyzer import BaseAnalyzer
from app.analyzers.financial_analyzer import FinancialAnalyzer
from app.analyzers.iot_analyzer import IoTAnalyzer
from app.analyzers.network_analyzer import NetworkAnalyzer
from app.analyzers.server_analyzer import ServerAnalyzer
from app.analyzers.student_analyzer import StudentAnalyzer
from app.analyzers.universal_analyzer import UniversalAnalyzer
from app.analyzers.website_analyzer import WebsiteAnalyzer

DOMAIN_ANALYZERS: list[BaseAnalyzer] = [
    ServerAnalyzer(),
    WebsiteAnalyzer(),
    NetworkAnalyzer(),
    IoTAnalyzer(),
    FinancialAnalyzer(),
    StudentAnalyzer(),
]
UNIVERSAL_ANALYZER = UniversalAnalyzer()


def get_analyzer(domain: str) -> BaseAnalyzer:
    for analyzer in DOMAIN_ANALYZERS:
        if analyzer.domain == domain:
            return analyzer
    return UNIVERSAL_ANALYZER


def supported_domains() -> list[dict]:
    return [
        {"domain": analyzer.domain, "title": analyzer.title, "description": analyzer.description,
         "risk_supported": analyzer.risk_supported,
         "roles": [{"name": role.name, "label": role.label, "core": role.core} for role in analyzer.roles]}
        for analyzer in DOMAIN_ANALYZERS
    ]
