from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    description: str | None
    qty: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    tax_amount: Decimal | None = None
    sub_ledger: str | None = None
    parent_ledger: str | None = None
    effective_ledger: str | None = None
    gl_mapping_source: str | None = None
    gl_mapping_confidence: float | None = None
    gl_mapping_reason: str | None = None
    extraction_source: str | None = None
    source_confidence: float | None = None
    fused_from: list[str] | None = None


class LineItemUpdateBody(BaseModel):
    id: int | None = None
    description: str | None = None
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    tax_amount: Decimal | None = None
    sub_ledger: str | None = None
    gl_mapping_source: str | None = Field(default=None, max_length=32)
    gl_mapping_confidence: Decimal | None = None
    gl_mapping_reason: str | None = None
