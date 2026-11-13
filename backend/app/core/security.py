"""Authentication helpers.

Two independent secrets:
  * access key (optional): protects the dashboard API on public deployments.
  * agent token: lets monitoring agents submit metrics.

Secrets are compared with hmac.compare_digest, which takes the same time
whether the first or the last character differs, so an attacker cannot guess a
secret character by character from response times.
"""

import hmac

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.errors import AppError


def secrets_match(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def require_access_key(
    x_access_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dependency for data endpoints. Does nothing when no access key is configured."""
    if not settings.access_key:
        return
    if not secrets_match(x_access_key, settings.access_key):
        raise AppError(401, "access_key_required", "A valid access key is required (enter it in Settings).")


def require_agent_token(
    x_agent_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.agent_token:
        raise AppError(503, "monitoring_disabled",
                       "Metric ingestion is disabled. Set NEXUSRAID_AGENT_TOKEN on the server to enable it.")
    if not secrets_match(x_agent_token, settings.agent_token):
        raise AppError(401, "invalid_agent_token", "The monitoring agent token is missing or wrong.")
