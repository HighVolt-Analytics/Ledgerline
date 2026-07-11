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
        tax_id = str(value.get("tax_id") or value.get("abn") or "").strip()
        return {
            "name": str(value.get("name") or value.get("vendor") or "").strip(),
            "tax_id": tax_id,
            "address": str(value.get("address") or "").strip(),
            "abn": tax_id,
        }
    if isinstance(value, str):
        return {"name": value.strip(), "tax_id": "", "address": "", "abn": ""}
    return {"name": "", "tax_id": "", "address": "", "abn": ""}


class LlmParty(BaseModel):
    name: str = ""
    tax_id: str = ""
    address: str = ""
    abn: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_party_input(cls, value: Any) -> Any:
        if value is None:
            return {"name": "", "tax_id": "", "address": "", "abn": ""}
        if isinstance(value, (dict, str)):
            return _coerce_party_dict(value)
        return value

    @model_validator(mode="after")
    def _sync_tax_id_abn(self) -> LlmParty:
        if self.tax_id and not self.abn:
            object.__setattr__(self, "abn", self.tax_id)
        elif self.abn and not self.tax_id:
            object.__setattr__(self, "tax_id", self.abn)
        return self


class FieldCitation(BaseModel):
  snippet: str = ""
  page: int | None = None


class LlmLineItem(BaseModel):
    description: str = ""
    amount: Decimal | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    tax_amount: Decimal | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_description(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("amount", "qty", "unit_price", "tax_amount", mode="before")
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
    so_reference: str = ""
    cost_centre: str = ""
    subtotal: Decimal | None = None
    gst: Decimal | None = None
    gst_rate: Decimal | None = None
    total: Decimal | None = None
    currency: str = ""
    abn: str = ""
    vendor: str = ""
    document_heading: str = ""
    bank_bsb: str = ""
    bank_account: str = ""
    bank_name: str = ""
    line_items: list[LlmLineItem] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    field_citations: dict[str, FieldCitation] = Field(default_factory=dict)
    extracted_fields: dict[str, str] = Field(default_factory=dict)
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
            "so_reference",
            "cost_centre",
            "currency",
            "abn",
            "vendor",
            "document_heading",
            "bank_bsb",
            "bank_account",
            "bank_name",
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

    @field_validator("subtotal", "gst", "gst_rate", "total", mode="before")
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
            return {"name": "", "tax_id": "", "address": "", "abn": ""}
        if isinstance(value, (dict, str)):
            return _coerce_party_dict(value)
        return value

    @field_validator("field_confidence", mode="before")
    @classmethod
    def _coerce_field_confidence(cls, value: Any) -> dict[str, float]:
        if value is None or isinstance(value, (int, float)):
            return {}
        if not isinstance(value, dict):
            return {}
        out: dict[str, float] = {}
        for key, score in value.items():
            token = str(key or "").strip().lower()
            if not token:
                continue
            try:
                out[token] = float(score)
            except (TypeError, ValueError):
                continue
        return out

    @field_validator("field_citations", mode="before")
    @classmethod
    def _coerce_field_citations(cls, value: Any) -> dict[str, FieldCitation]:
        if value is None or not isinstance(value, dict):
            return {}
        out: dict[str, FieldCitation] = {}
        for key, citation in value.items():
            token = str(key or "").strip().lower()
            if not token:
                continue
            if isinstance(citation, FieldCitation):
                out[token] = citation
            elif isinstance(citation, dict):
                out[token] = FieldCitation(
                    snippet=str(citation.get("snippet") or "").strip(),
                    page=citation.get("page"),
                )
        return out
