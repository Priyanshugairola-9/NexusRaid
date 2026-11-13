"""Request/response shapes for datasets and analyses."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    # Optional per-run overrides of the saved analysis settings (see AnalysisConfig).
    config: dict | None = Field(default=None, description="Setting overrides for this run only.")


class AnalysisSettingsIn(BaseModel):
    config: dict = Field(description="Analysis settings to save as defaults.")
