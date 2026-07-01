"""LLM runtime document classification + extraction contract."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _parse_optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        value = token.replace(",", "")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _coerce_party_dict(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "name": str(value.get("name") or value.get("vendor") or "").strip(),
            "abn": str(value.get("abn") or "").strip(),
        }
    if isinstance(value, str):
        return {"name": value.strip(), "abn": ""}
    return {"name": "", "abn": ""}


class LlmParty(BaseModel):
    name: str = ""
    abn: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_party_input(cls, value: Any) -> Any:
        if value is None:
            return {"name": "", "abn": ""}
        if isinstance(value, (dict, str)):
            return _coerce_party_dict(value)
        return value


class LlmLineItem(BaseModel):
    description: str = ""
    amount: Decimal | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_description(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("amount", "qty", "unit_price", mode="before")
    @classmethod
    def _coerce_decimal_fields(cls, value: Any) -> Decimal | None:
        return _parse_optional_decimal(value)


class LlmDocumentResult(BaseModel):
    suggested_dt: str = Field(default="", description="DT-xx catalogue code")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    seller: LlmParty = Field(default_factory=LlmParty)
    buyer: LlmParty = Field(default_factory=LlmParty)
    perspective: str = Field(default="unknown", description="purchase | sales | unknown")
    invoice_no: str = ""
    invoice_date: str = ""
    due_date: str = ""
    po_reference: str = ""
    subtotal: Decimal | None = None
    gst: Decimal | None = None
    total: Decimal | None = None
    currency: str = "AUD"
    abn: str = ""
    vendor: str = ""
    document_heading: str = ""
    line_items: list[LlmLineItem] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_optional_strings(cls, value: Any) -> Any:
        """LLMs often emit null for fields that do not apply to the document type."""
        if not isinstance(value, dict):
            return value
        out = dict(value)
        for key in (
            "reasoning",
            "invoice_no",
            "invoice_date",
            "due_date",
            "po_reference",
            "currency",
            "abn",
            "document_heading",
        ):
            if out.get(key) is None:
                out[key] = ""
        items = out.get("line_items")
        if isinstance(items, list):
            cleaned: list[dict[str, Any]] = []
            for row in items:
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                if item.get("description") is None:
                    item["description"] = ""
                cleaned.append(item)
            out["line_items"] = cleaned
        return out

    @field_validator("suggested_dt", mode="before")
    @classmethod
    def _normalize_dt(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @field_validator("perspective", mode="before")
    @classmethod
    def _normalize_perspective(cls, value: Any) -> str:
        token = str(value or "unknown").strip().lower()
        if token in {"purchase", "sales", "unknown"}:
            return token
        return "unknown"

    @field_validator("subtotal", "gst", "total", mode="before")
    @classmethod
    def _coerce_money_fields(cls, value: Any) -> Decimal | None:
        return _parse_optional_decimal(value)

    @field_validator("vendor", mode="before")
    @classmethod
    def _normalize_vendor(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            return str(value.get("name") or value.get("vendor") or "").strip()
        return str(value).strip()

    @field_validator("seller", "buyer", mode="before")
    @classmethod
    def _coerce_parties(cls, value: Any) -> Any:
        if value is None:
            return {"name": "", "abn": ""}
        if isinstance(value, (dict, str)):
            return _coerce_party_dict(value)
        return value
