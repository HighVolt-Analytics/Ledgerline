"""Line-item GL display helpers — parent ledger from doc type, effective segment."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.schemas.line_item import LineItemResponse
from app.schemas.rule_book_config import RuleBookConfigPayload, VendorMaster
from app.services.classification.document_type_post_to_service import resolve_document_type_post_to
from app.services.classification.document_type_playbook_profile_service import (
    gl_posting_applicable_for_invoice,
)
from app.services.master_data.chart_of_accounts_service import sub_ledger_exists
from app.services.shared.amount_sanity import plausible_confidence


def resolve_parent_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> str:
    post_to = resolve_document_type_post_to(invoice, config)
    if post_to is not None:
        ledger = (post_to.ledger or "").strip()
        if ledger:
            return ledger
    return (invoice.account_name or "").strip()


def resolve_doc_type_default_sub_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> str:
    post_to = resolve_document_type_post_to(invoice, config)
    if post_to is None:
        return ""
    return (post_to.sub_ledger or "").strip()


def resolve_vendor_default_sub_ledger(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    parent_ledger: str,
) -> str:
    vendor_name = (invoice.vendor or "").strip().lower()
    if not vendor_name:
        return ""
    parent = parent_ledger.strip().lower()
    for master in config.vendor_masters:
        name = (master.name or "").strip().lower()
        if not name or name != vendor_name:
            continue
        default_ledger = (master.default_ledger or "").strip()
        if default_ledger in {"", "—"}:
            continue
        if default_ledger.lower() != parent:
            continue
        return (master.default_sub_ledger or "").strip()
    return ""


def effective_line_ledger(*, sub_ledger: str | None, parent_ledger: str) -> str:
    sub = (sub_ledger or "").strip()
    if sub:
        return sub
    return parent_ledger.strip()


def build_line_item_response(
    line: LineItem,
    *,
    parent_ledger: str,
) -> LineItemResponse:
    parent = parent_ledger.strip()
    sub = (line.sub_ledger or "").strip() or None
    confidence = line.gl_mapping_confidence
    return LineItemResponse(
        id=line.id,
        invoice_id=line.invoice_id,
        description=line.description,
        qty=line.qty,
        unit_price=line.unit_price,
        amount=line.amount,
        tax_amount=line.tax_amount,
        sub_ledger=sub,
        parent_ledger=parent or None,
        effective_ledger=effective_line_ledger(sub_ledger=sub, parent_ledger=parent) or None,
        gl_mapping_source=line.gl_mapping_source,
        gl_mapping_confidence=float(confidence) if confidence is not None else None,
        gl_mapping_reason=line.gl_mapping_reason,
    )


def build_line_item_responses(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> list[LineItemResponse]:
    parent = resolve_parent_ledger(invoice, config)
    return [build_line_item_response(line, parent_ledger=parent) for line in invoice.line_items]


def line_gl_mapping_applicable(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    if not gl_posting_applicable_for_invoice(
        invoice,
        document_types=list(config.document_types),
    ):
        return False
    return bool(resolve_parent_ledger(invoice, config))


def validate_sub_ledger_for_parent(
    sub_ledger: str,
    *,
    parent_ledger: str,
    accounts: list,
) -> bool:
    cleaned = (sub_ledger or "").strip()
    if not cleaned:
        return True
    return sub_ledger_exists(parent_ledger, cleaned, accounts)


def apply_sub_ledger_to_line(
    line: LineItem,
    *,
    sub_ledger: str,
    source: str,
    confidence: Decimal | float | None = None,
    reason: str | None = None,
) -> None:
    line.sub_ledger = (sub_ledger or "").strip() or None
    line.gl_mapping_source = source
    line.gl_mapping_confidence = plausible_confidence(confidence)
    line.gl_mapping_reason = (reason or "").strip() or None
