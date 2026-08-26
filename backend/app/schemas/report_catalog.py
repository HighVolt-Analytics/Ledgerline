"""Catalog, preview, export, and favourites shapes for the Reports page."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReportRange = Literal["month", "quarter", "custom"]
ReportExportFormat = Literal["pdf", "xlsx"]
ReportCategory = Literal[
    "payables_receivables",
    "budgets_performance",
    "transactions",
    "exceptions_controls",
]


class ReportCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    category: ReportCategory
    supports_compare: bool = False


class ReportCatalogResponse(BaseModel):
    reports: list[ReportCatalogItem]
    favourite_ids: list[str] = Field(default_factory=list)


class ReportFavouritesUpdate(BaseModel):
    report_ids: list[str] = Field(default_factory=list)


class ReportPreviewRow(BaseModel):
    cells: list[str]
    emphasize: bool = False


class ReportPreview(BaseModel):
    report_id: str
    title: str
    period_label: str
    currency: str = ""
    columns: list[str]
    rows: list[ReportPreviewRow] = Field(default_factory=list)
    compare_columns: list[str] | None = None
    empty: bool = False
    notes: str | None = None


class ReportExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    format: ReportExportFormat
    range: ReportRange = "month"
    compare: bool = False
    date_from: date | None = Field(default=None, alias="from")
    date_to: date | None = Field(default=None, alias="to")
    layout_id: int | None = None


class ReportColumnConfig(BaseModel):
    columns: list[str] = Field(min_length=1)

    @field_validator("columns")
    @classmethod
    def _unique_nonempty(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            key = str(raw or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        if not cleaned:
            raise ValueError("column_config.columns must include at least one key")
        return cleaned


class ReportColumnLayoutCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    column_config: ReportColumnConfig
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class ReportColumnLayoutUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    column_config: ReportColumnConfig | None = None

    @field_validator("name")
    @classmethod
    def _strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class ReportColumnLayoutItem(BaseModel):
    id: int
    report_id: str
    name: str
    column_config: ReportColumnConfig
    is_default: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
