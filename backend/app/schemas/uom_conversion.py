"""Purchase three-way match settings (qty tolerance only; UOM deferred)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PurchaseMatchConfig(BaseModel):
    """Global purchase matching — quantity tolerance for three-way match."""

    qty_tolerance_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        alias="qtyTolerancePct",
        description="Allow invoice qty up to GRN qty × (1 + pct/100) before qty variance",
    )

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
