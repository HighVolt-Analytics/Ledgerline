"""Dashboard API query parameters."""

from pydantic import BaseModel, ConfigDict, Field


class DashboardOverviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity_limit: int = Field(8, ge=1, le=50)
    month: str | None = Field(
        None,
        description="Period as YYYY-MM (defaults to current month)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    )


class DashboardActivityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = Field(20, ge=1, le=100)
