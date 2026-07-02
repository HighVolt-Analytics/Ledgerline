"""Finance-accurate counterparty resolution — AP vendor vs AR customer on invoice.vendor."""

from __future__ import annotations

from typing import Any

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.document_type_catalog import ROUTE_EXPENSES, ROUTE_PURCHASE, ROUTE_SALES
from app.services.extraction_field_values import extracted_fields_from_invoice
from app.services.invoice_data import InvoiceData
from app.services.tenant_org_context import OrgContext, infer_perspective, org_context_from_config, party_matches_tenant
from app.services.vendor_name_utils import extract_customer_party_from_text, normalize_vendor_name, pick_best_vendor_name

CounterpartySide = str  # "vendor" | "customer" | "party"


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
    return normalize_vendor_name(str(block.get("name") or ""))


def _candidate_names(*values: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = normalize_vendor_name(value)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


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
) -> str | None:
    """
    Pick the finance counterparty for invoice.vendor.

    - customer (AR / sales): buyer, excluding tenant org
    - vendor (AP / purchase): seller/supplier, excluding tenant org
    """
    buyer = normalize_vendor_name(buyer_name)
    seller = normalize_vendor_name(seller_name)
    generic = normalize_vendor_name(generic_name)

    if side == "customer":
        text_customer = extract_customer_party_from_text(document_text or "")
        ordered = _candidate_names(buyer, text_customer)
        if generic and not party_matches_tenant(generic, seller_abn or buyer_abn or "", org):
            ordered.extend(_candidate_names(generic))
        for name in ordered:
            if not party_matches_tenant(name, buyer_abn or "", org):
                return name
        return buyer or text_customer or generic

    if side == "vendor":
        ordered = _candidate_names(seller, generic, buyer)
        for name in ordered:
            if not party_matches_tenant(name, seller_abn or "", org):
                return name
        return seller or generic

    return pick_best_vendor_name(generic, buyer, seller)


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
    buyer_abn = fields.get("buyer_abn") or str((raw.get("buyer") or {}).get("abn") or "")
    seller_abn = fields.get("seller_abn") or str((raw.get("seller") or {}).get("abn") or "")

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
