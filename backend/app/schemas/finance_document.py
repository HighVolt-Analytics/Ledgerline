"""Normalized finance document schema (cross document-type)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class FinanceLineItem(BaseModel):
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_amount: Decimal | None = None
    source: str | None = None
    source_confidence: float | None = None


class FinanceDocumentNormalized(BaseModel):
    document_type: str
    vendor_name: str | None = None
    buyer_name: str | None = None
    document_number: str | None = None
    document_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    amount_due: Decimal | None = None
    reference_numbers: dict[str, str] = Field(default_factory=dict)
    line_items: list[FinanceLineItem] = Field(default_factory=list)
    parties: dict[str, str] = Field(default_factory=dict)
    payment_details: dict[str, str] = Field(default_factory=dict)
    source_model: str | None = None
    source_confidence: float | None = None
    field_confidence: dict[str, float | None] = Field(default_factory=dict)
    field_sources: dict[str, str] = Field(default_factory=dict)
    review_reasons: list[str] = Field(default_factory=list)
    confirmed_dt: str | None = None
    extraction_route: str | None = None

    def model_dump_jsonable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
