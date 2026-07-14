"""Finance-accurate counterparty resolution — AP vendor vs AR customer on invoice.vendor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.classification.document_type_catalog import ROUTE_EXPENSES, ROUTE_PURCHASE, ROUTE_SALES
from app.services.extraction.extraction_field_values import extracted_fields_from_invoice
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext, infer_perspective, org_context_from_config, party_matches_tenant
from app.services.master_data.vendor_name_utils import (
    dedupe_repeated_vendor_phrase,
    extract_customer_party_from_text,
    is_plausible_vendor_name,
    normalize_vendor_name,
    pick_best_vendor_name,
    strip_vendor_name_contamination,
)

CounterpartySide = str  # "vendor" | "customer" | "party"


@dataclass(frozen=True)
class CounterpartyResolution:
    """Resolved finance counterparty with edge-case signals."""

    name: str | None
    ambiguous: bool = False
    reasons: tuple[str, ...] = ()
    side: CounterpartySide = "party"


def counterparty_side_for_route(route_target: str | None) -> CounterpartySide:
    route = (route_target or "").strip()
    if route == ROUTE_SALES:
        return "customer"
    if route in {ROUTE_PURCHASE, ROUTE_EXPENSES}:
        return "vendor"
    return "party"


def counterparty_side_for_perspective(perspective: str | None) -> CounterpartySide:
    token = (perspective or "").strip().lower()
    if token == "sales":
        return "customer"
    if token == "purchase":
        return "vendor"
    return "party"


def _party_name_from_raw_block(raw: dict[str, Any], key: str) -> str | None:
    block = raw.get(key)
    if not isinstance(block, dict):
        return None
    return _display_party_name(str(block.get("name") or ""))


def _display_party_name(value: str | None) -> str | None:
    """Clean contamination but keep legal suffixes for stored counterparty labels."""
    import re

    if not value:
        return None
    deduped = dedupe_repeated_vendor_phrase(str(value))
    cleaned = strip_vendor_name_contamination(deduped)
    if not is_plausible_vendor_name(cleaned):
        return None
    collapsed = re.sub(r"\s+", " ", cleaned.strip())
    return collapsed or None


def _candidate_entries(*values: str | None) -> list[tuple[str, str]]:
    """Return (match_key, display_name) pairs; match_key is suffix-stripped for compare."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for value in values:
        display = _display_party_name(value)
        if not display:
            continue
        match_key = (normalize_vendor_name(display) or display).lower()
        if match_key in seen:
            continue
        seen.add(match_key)
        out.append((match_key, display))
    return out


def _tax_id_for_display(
    display: str,
    *,
    buyer_display: str,
    seller_display: str,
    buyer_abn: str,
    seller_abn: str,
) -> str:
    left = (normalize_vendor_name(display) or display).lower()
    buyer_key = (normalize_vendor_name(buyer_display) or buyer_display).lower()
    seller_key = (normalize_vendor_name(seller_display) or seller_display).lower()
    if buyer_key and left == buyer_key:
        return buyer_abn
    if seller_key and left == seller_key:
        return seller_abn
    return seller_abn or buyer_abn


def _first_non_tenant(
    ordered: list[tuple[str, str]],
    *,
    org: OrgContext,
    buyer_display: str,
    seller_display: str,
    buyer_abn: str,
    seller_abn: str,
) -> str | None:
    for _key, display in ordered:
        if not is_plausible_vendor_name(display):
            continue
        tax_id = _tax_id_for_display(
            display,
            buyer_display=buyer_display,
            seller_display=seller_display,
            buyer_abn=buyer_abn,
            seller_abn=seller_abn,
        )
        if not party_matches_tenant(display, tax_id, org):
            return display
    return None


def resolve_counterparty_resolution(
    *,
    side: CounterpartySide,
    org: OrgContext,
    buyer_name: str | None = None,
    buyer_abn: str | None = None,
    seller_name: str | None = None,
    seller_abn: str | None = None,
    generic_name: str | None = None,
    document_text: str | None = None,
    perspective: str | None = None,
) -> CounterpartyResolution:
    """
    Pick the finance counterparty for invoice.vendor.

    - customer (AR / sales): buyer, excluding tenant org (seller fallback on label swap)
    - vendor (AP / purchase): seller/supplier, excluding tenant org
    Never returns the tenant's own name when a third party exists; otherwise ambiguous.
    """
    buyer_display = _display_party_name(buyer_name) or ""
    seller_display = _display_party_name(seller_name) or ""
    generic_display = _display_party_name(generic_name) or ""
    buyer_tid = (buyer_abn or "").strip()
    seller_tid = (seller_abn or "").strip()
    reasons: list[str] = []

    if (perspective or "").strip().lower() == "unknown":
        reasons.append("perspective_unknown")

    if side == "customer":
        text_customer = extract_customer_party_from_text(document_text or "")
        ordered = _candidate_entries(buyer_display, text_customer)
        if generic_display and not party_matches_tenant(
            generic_display, seller_tid or buyer_tid, org
        ):
            ordered.extend(_candidate_entries(generic_display))
        # Label-swap edge case: buyer is us / empty → seller is the real customer.
        if seller_display and (
            not buyer_display
            or party_matches_tenant(buyer_display, buyer_tid, org)
        ):
            ordered.extend(_candidate_entries(seller_display))
        picked = _first_non_tenant(
            ordered,
            org=org,
            buyer_display=buyer_display,
            seller_display=seller_display,
            buyer_abn=buyer_tid,
            seller_abn=seller_tid,
        )
        if picked:
            return CounterpartyResolution(
                name=picked, ambiguous=bool(reasons), reasons=tuple(reasons), side=side
            )
        if buyer_display and not party_matches_tenant(buyer_display, buyer_tid, org):
            return CounterpartyResolution(
                name=buyer_display, ambiguous=bool(reasons), reasons=tuple(reasons), side=side
            )
        reasons.append("counterparty_self_or_missing")
        return CounterpartyResolution(name=None, ambiguous=True, reasons=tuple(reasons), side=side)

    if side == "vendor":
        ordered = _candidate_entries(seller_display, generic_display, buyer_display)
        picked = _first_non_tenant(
            ordered,
            org=org,
            buyer_display=buyer_display,
            seller_display=seller_display,
            buyer_abn=buyer_tid,
            seller_abn=seller_tid,
        )
        if picked:
            return CounterpartyResolution(
                name=picked, ambiguous=bool(reasons), reasons=tuple(reasons), side=side
            )
        if seller_display and not party_matches_tenant(seller_display, seller_tid, org):
            return CounterpartyResolution(
                name=seller_display, ambiguous=bool(reasons), reasons=tuple(reasons), side=side
            )
        reasons.append("counterparty_self_or_missing")
        return CounterpartyResolution(name=None, ambiguous=True, reasons=tuple(reasons), side=side)

    ordered = _candidate_entries(generic_display, buyer_display, seller_display)
    picked = _first_non_tenant(
        ordered,
        org=org,
        buyer_display=buyer_display,
        seller_display=seller_display,
        buyer_abn=buyer_tid,
        seller_abn=seller_tid,
    )
    if picked:
        if (perspective or "").strip().lower() in {"", "unknown", "party"}:
            reasons.append("side_unknown")
        return CounterpartyResolution(
            name=picked,
            ambiguous=bool(reasons),
            reasons=tuple(reasons),
            side=side,
        )
    best = pick_best_vendor_name(
        generic_display or None, buyer_display or None, seller_display or None
    )
    best_display = _display_party_name(best) if best else None
    if best_display and not party_matches_tenant(best_display, seller_tid or buyer_tid, org):
        return CounterpartyResolution(
            name=best_display, ambiguous=True, reasons=("side_unknown",), side=side
        )
    reasons.append("counterparty_self_or_missing")
    return CounterpartyResolution(name=None, ambiguous=True, reasons=tuple(reasons), side=side)


def resolve_counterparty_name(
    *,
    side: CounterpartySide,
    org: OrgContext,
    buyer_name: str | None = None,
    buyer_abn: str | None = None,
    seller_name: str | None = None,
    seller_abn: str | None = None,
    generic_name: str | None = None,
    document_text: str | None = None,
    perspective: str | None = None,
) -> str | None:
    """Pick the finance counterparty for invoice.vendor (name only)."""
    return resolve_counterparty_resolution(
        side=side,
        org=org,
        buyer_name=buyer_name,
        buyer_abn=buyer_abn,
        seller_name=seller_name,
        seller_abn=seller_abn,
        generic_name=generic_name,
        document_text=document_text,
        perspective=perspective,
    ).name


def resolve_counterparty_side(
    *,
    route_target: str | None,
    perspective: str | None,
) -> CounterpartySide:
    route_side = counterparty_side_for_route(route_target)
    if route_side != "party":
        return route_side
    return counterparty_side_for_perspective(perspective)


def resolve_counterparty_from_invoice_context(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None,
    parsed: InvoiceData | None = None,
    org: OrgContext | None = None,
) -> str | None:
    fields = extracted_fields_from_invoice(invoice)
    raw = parsed.raw_fields if parsed is not None and isinstance(parsed.raw_fields, dict) else {}

    buyer_name = fields.get("buyer_name") or _party_name_from_raw_block(raw, "buyer")
    seller_name = fields.get("seller_name") or _party_name_from_raw_block(raw, "seller")
    buyer_abn = (
        fields.get("buyer_tax_id")
        or fields.get("buyer_abn")
        or str((raw.get("buyer") or {}).get("tax_id") or (raw.get("buyer") or {}).get("abn") or "")
    )
    seller_abn = (
        fields.get("seller_tax_id")
        or fields.get("seller_abn")
        or str((raw.get("seller") or {}).get("tax_id") or (raw.get("seller") or {}).get("abn") or "")
    )

    perspective = fields.get("perspective") or fields.get("llm_perspective")
    if not perspective and parsed is not None:
        perspective = str(raw.get("llm_perspective") or "")

    org_ctx = org or org_context_from_config(config, None)
    if not perspective or perspective == "unknown":
        perspective = infer_perspective(
            org=org_ctx,
            seller_name=seller_name or "",
            seller_abn=seller_abn or "",
            buyer_name=buyer_name or "",
            buyer_abn=buyer_abn or "",
            llm_perspective=str(perspective or "unknown"),
        )

    side = resolve_counterparty_side(
        route_target=invoice.route_target,
        perspective=perspective,
    )
    generic = (invoice.vendor or (parsed.vendor if parsed else None) or "").strip() or None
    document_text = (
        (parsed.document_text if parsed else None)
        or invoice.document_text
        or ""
    )

    return resolve_counterparty_name(
        side=side,
        org=org_ctx,
        buyer_name=buyer_name,
        buyer_abn=buyer_abn,
        seller_name=seller_name,
        seller_abn=seller_abn,
        generic_name=generic,
        document_text=document_text,
        perspective=perspective,
    )


def sync_invoice_counterparty(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None,
    parsed: InvoiceData | None = None,
    org: OrgContext | None = None,
) -> str | None:
    """Persist finance-correct counterparty on invoice.vendor."""
    resolved = resolve_counterparty_from_invoice_context(
        invoice,
        config=config,
        parsed=parsed,
        org=org,
    )
    if resolved:
        invoice.vendor = resolved
    return resolved
