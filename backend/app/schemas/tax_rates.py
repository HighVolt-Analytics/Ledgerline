"""Tenant tax rates. When a bill-processing platform is connected, Settings lists that platform's rates."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

TaxRateReportType = Literal[
    "SALES",
    "PURCHASES",
    "GST_FREE_SALES",
    "EXEMPT_INCOME",
    "BAS_EXCLUDED",
    "GST_FREE_EXPENSES",
]

TAX_RATE_REPORT_TYPES: tuple[TaxRateReportType, ...] = (
    "SALES",
    "PURCHASES",
    "GST_FREE_SALES",
    "EXEMPT_INCOME",
    "BAS_EXCLUDED",
    "GST_FREE_EXPENSES",
)


class TaxRateComponent(BaseModel):
    """One named percentage inside a tax rate (Xero TaxComponents)."""

    name: str = Field(..., min_length=1, max_length=50)
    rate: float = Field(..., ge=0, le=100)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("rate")
    @classmethod
    def _four_decimals(cls, value: float) -> float:
        return round(float(value), 4)


class TaxRateEntry(BaseModel):
    """Org tax rate: display name, Activity Statement type, and components."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    display_name: str = Field(..., min_length=1, max_length=50)
    tax_type: str = Field(..., min_length=1, max_length=64)
    components: list[TaxRateComponent] = Field(..., min_length=1)
    can_delete: bool = True
    can_edit: bool = True
    xero_tax_type: str | None = None
    status: str | None = None
    source: Literal["xero", "local", "quickbooks_online"] = "local"

    @field_validator("id", mode="before")
    @classmethod
    def _ensure_id(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return str(uuid.uuid4())
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @computed_field
    @property
    def total_rate(self) -> float:
        return round(sum(item.rate for item in self.components), 4)


class BillProcessingTaxProvider(BaseModel):
    """Which bill-processing platform currently owns tax rates in Settings."""

    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    organisation_name: str | None = None
    connected: bool = True


class TaxRatesResponse(BaseModel):
    tax_rates: list[TaxRateEntry] = Field(default_factory=list)
    xero_connected: bool = False
    source: Literal["none", "xero", "quickbooks_online"] = "none"
    provider: BillProcessingTaxProvider | None = None

    @classmethod
    def from_entries(
        cls,
        entries: list[TaxRateEntry],
        *,
        xero_connected: bool = False,
        source: Literal["none", "xero", "quickbooks_online"] | None = None,
        provider: BillProcessingTaxProvider | None = None,
    ) -> "TaxRatesResponse":
        resolved_source: Literal["none", "xero", "quickbooks_online"] = source or (
            "xero" if xero_connected else "none"
        )
        return cls(
            tax_rates=list(entries),
            xero_connected=resolved_source == "xero",
            source=resolved_source,
            provider=provider,
        )


class CreateTaxRateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)
    tax_type: TaxRateReportType
    components: list[TaxRateComponent] = Field(..., min_length=1)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class UpdateTaxRateRequest(CreateTaxRateRequest):
    """Same fields as create — used to update one rate."""


class UpdateTaxRatesRequest(BaseModel):
    tax_rates: list[TaxRateEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names_and_ids(self) -> "UpdateTaxRatesRequest":
        names = [item.display_name.strip().lower() for item in self.tax_rates]
        if len(names) != len(set(names)):
            raise ValueError("tax rate display names must be unique")
        ids = [item.id.strip() for item in self.tax_rates]
        if len(ids) != len(set(ids)):
            raise ValueError("tax rate ids must be unique")
        allowed = set(TAX_RATE_REPORT_TYPES)
        for item in self.tax_rates:
            if item.tax_type not in allowed:
                raise ValueError(f"invalid tax type {item.tax_type!r}")
        return self

    def to_entries(self) -> list[TaxRateEntry]:
        return list(self.tax_rates)
