"""Fiscal period lock API."""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class FiscalPeriodResponse(BaseModel):
    id: int
    period_start: date
    period_end: date
    status: str
    closed_at: datetime | None = None
    closed_by: int | None = None
    reopened_at: datetime | None = None
    reopened_by: int | None = None

    model_config = {"from_attributes": True}


class ClosePeriodRequest(BaseModel):
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _range_valid(self) -> "ClosePeriodRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class ListFiscalPeriodsResponse(BaseModel):
    periods: list[FiscalPeriodResponse] = Field(default_factory=list)
