"""Unit-of-measure conversion rules for purchase three-way match."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class UomConversionRule(BaseModel):
    """Convert vendor/SKU quantities into a common base unit (e.g. EA)."""

    id: str = Field(..., min_length=1, max_length=64)
    vendor_key: str = Field(default="", max_length=100, alias="vendorKey")
    sku: str = Field(default="", max_length=100)
    from_uom: str = Field(..., min_length=1, max_length=32, alias="fromUom")
    to_uom: str = Field(default="EA", min_length=1, max_length=32, alias="toUom")
    factor: Decimal = Field(
        ...,
        gt=0,
        description="1 from_uom equals this many to_uom (e.g. 1 CTN = 12 EA → factor 12)",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("from_uom", "to_uom", mode="before")
    @classmethod
    def _strip_uom(cls, value: object) -> str:
        return str(value or "").strip().upper()


class PurchaseMatchConfig(BaseModel):
    """Global purchase matching — UOM table and quantity tolerance."""

    base_uom: str = Field(default="EA", alias="baseUom")
    qty_tolerance_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        alias="qtyTolerancePct",
        description="Allow invoice qty up to GRN qty × (1 + pct/100) before qty variance",
    )
    uom_conversions: list[UomConversionRule] = Field(default_factory=list, alias="uomConversions")

    model_config = {"populate_by_name": True, "extra": "ignore"}


def normalize_purchase_match_config(value: object | None) -> PurchaseMatchConfig:
    if value is None:
        return PurchaseMatchConfig()
    if isinstance(value, PurchaseMatchConfig):
        return value
    if isinstance(value, dict):
        try:
            return PurchaseMatchConfig.model_validate(value)
        except Exception:
            return PurchaseMatchConfig()
    return PurchaseMatchConfig()
