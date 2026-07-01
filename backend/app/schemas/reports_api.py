"""Reports API query parameters."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class ReportsAnalyticsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    month: str | None = Field(
        None,
        description="Period as YYYY-MM (defaults to current month)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    )


class ReportsDocumentsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_from: date | None = Field(None, description="Inclusive start of invoice date range")
    date_to: date | None = Field(None, description="Inclusive end of invoice date range")


class ReportsWorkbookRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    workbook_date: date | None = Field(
        None, description="Legacy: single invoice date (same as date_from=date_to)"
    )
    date_from: date | None = Field(None, description="Inclusive start of invoice date range")
    date_to: date | None = Field(None, description="Inclusive end of invoice date range")
