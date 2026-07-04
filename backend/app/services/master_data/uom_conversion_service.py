"""Normalize PO / GRN / invoice quantities to a common base unit for three-way match."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Sequence

from app.schemas.uom_conversion import PurchaseMatchConfig, UomConversionRule

_UOM_ALIASES: dict[str, str] = {
    "CARTON": "CTN",
    "CARTONS": "CTN",
    "CTNS": "CTN",
    "CTN": "CTN",
    "BOX": "CTN",
    "BOXES": "CTN",
    "UNIT": "EA",
    "UNITS": "EA",
    "EACH": "EA",
    "EA": "EA",
    "PCS": "EA",
    "PC": "EA",
    "PIECE": "EA",
    "PIECES": "EA",
}

_UOM_IN_TEXT = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*(cartons?|ctns?|boxes?|units?|each|ea|pcs?|pieces?)\b"
)


def normalize_uom_token(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    token = re.sub(r"[^A-Za-z0-9]", "", str(raw).strip()).upper()
    if not token:
        return None
    return _UOM_ALIASES.get(token, token)


def infer_uom_from_description(description: str | None) -> str | None:
    if not description:
        return None
    match = _UOM_IN_TEXT.search(description)
    if not match:
        return None
    return normalize_uom_token(match.group(2))


def _vendor_key(vendor: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (vendor or "").strip().lower()).strip("-")


def _lookup_factor(
    *,
    from_uom: str,
    to_uom: str,
    vendor: str | None,
    sku: str | None,
    rules: Sequence[UomConversionRule],
) -> Decimal | None:
    src = normalize_uom_token(from_uom)
    dst = normalize_uom_token(to_uom)
    if not src or not dst:
        return None
    if src == dst:
        return Decimal("1")

    vendor_token = _vendor_key(vendor)
    sku_token = (sku or "").strip().upper()

    def score(rule: UomConversionRule) -> tuple[int, int]:
        rule_vendor = (rule.vendor_key or "").strip().lower()
        rule_sku = (rule.sku or "").strip().upper()
        vendor_match = 2 if rule_vendor and rule_vendor == vendor_token else (
            1 if not rule_vendor else 0
        )
        sku_match = 2 if rule_sku and rule_sku == sku_token else (1 if not rule_sku else 0)
        return (vendor_match, sku_match)

    candidates = [
        rule
        for rule in rules
        if normalize_uom_token(rule.from_uom) == src
        and normalize_uom_token(rule.to_uom) == dst
    ]
    if not candidates:
        return None
    best = max(candidates, key=score)
    if score(best)[0] == 0:
        return None
    return Decimal(str(best.factor))


def convert_qty_to_base(
    qty: Decimal | float | int | None,
    uom: str | None,
    *,
    vendor: str | None = None,
    sku: str | None = None,
    config: PurchaseMatchConfig | None = None,
) -> Decimal:
    """Return quantity in config.base_uom (default EA)."""
    cfg = config or PurchaseMatchConfig()
    base = normalize_uom_token(cfg.base_uom) or "EA"
    amount = Decimal(str(qty or 0))
    if amount <= 0:
        return Decimal("0")

    src = normalize_uom_token(uom) or base
    if src == base:
        return amount

    factor = _lookup_factor(
        from_uom=src,
        to_uom=base,
        vendor=vendor,
        sku=sku,
        rules=cfg.uom_conversions,
    )
    if factor is None:
        return amount
    return amount * factor


def unit_price_per_base(
    qty: Decimal | float | int | None,
    unit_price: Decimal | float | int | None,
    uom: str | None,
    *,
    vendor: str | None = None,
    sku: str | None = None,
    config: PurchaseMatchConfig | None = None,
) -> Decimal:
    """Unit price expressed per base UOM (e.g. price per EA)."""
    cfg = config or PurchaseMatchConfig()
    base = normalize_uom_token(cfg.base_uom) or "EA"
    src = normalize_uom_token(uom) or base
    price = Decimal(str(unit_price or 0))
    if price <= 0:
        return Decimal("0")
    if src == base:
        return price
    factor = _lookup_factor(
        from_uom=src,
        to_uom=base,
        vendor=vendor,
        sku=sku,
        rules=cfg.uom_conversions,
    )
    if factor is None or factor <= 0:
        return price
    return price / factor


def qty_over_billing(
    invoice_base_qty: Decimal,
    grn_base_qty: Decimal,
    *,
    tolerance_pct: float = 0.0,
) -> bool:
    """True when invoice exceeds GRN qty beyond configured tolerance."""
    if grn_base_qty <= 0:
        return invoice_base_qty > 0
    allowed = grn_base_qty * (Decimal("1") + Decimal(str(tolerance_pct)) / Decimal("100"))
    return invoice_base_qty > allowed


def invoice_base_qty(
    invoice,
    *,
    config: PurchaseMatchConfig | None = None,
) -> Decimal:
    """Sum line quantities normalized to base UOM."""
    total = Decimal("0")
    lines = getattr(invoice, "line_items", None) or []
    vendor = getattr(invoice, "vendor", None)
    if not lines:
        return Decimal("1")
    for line in lines:
        qty = getattr(line, "qty", None)
        uom = getattr(line, "uom", None) or infer_uom_from_description(
            getattr(line, "description", None)
        )
        sku = getattr(line, "sku", None)
        total += convert_qty_to_base(qty, uom, vendor=vendor, sku=sku, config=config)
    if total <= 0:
        return Decimal("1")
    return total
