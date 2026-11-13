"""Response shape of the health-check endpoint."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    database: Literal["ok", "unavailable"]
    storage: Literal["ok", "unavailable"]
