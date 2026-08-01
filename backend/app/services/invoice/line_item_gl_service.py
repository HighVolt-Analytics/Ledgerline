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


def resolve_effective_ledger_mapping(
    *,
    parent_ledger: str,
    effective_ledger: str,
    config: RuleBookConfigPayload,
) -> "AccountMapping":
    """Map parent or nested sub-ledger name to a journal AccountMapping."""
    from app.services.master_data.chart_of_accounts_service import sub_ledgers_for_ledger
    from app.services.rule_book.account_mapper import AccountMapping, resolve_category_for_config

    parent = resolve_category_for_config(parent_ledger, config)
    eff = (effective_ledger or "").strip()
    parent_name = (parent.account_name or "").strip()
    if not eff or eff.lower() == parent_name.lower():
        return parent

    for sub in sub_ledgers_for_ledger(parent_ledger, list(config.chart_of_accounts or [])):
        if sub.name.strip().lower() == eff.lower():
            sub_code = (sub.code or "").strip()
            account_code = (
                f"{parent.account_code}-{sub_code}" if sub_code else parent.account_code
            )
            return AccountMapping(
                account_code,
                sub.name.strip(),
                expense_category=sub.name.strip(),
            )

    flat = resolve_category_for_config(eff, config)
    if (flat.account_code or "").strip() not in {"", "9999"}:
        return flat
    return parent


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
        extraction_source=line.extraction_source,
        source_confidence=(
            float(line.source_confidence) if line.source_confidence is not None else None
        ),
        fused_from=list(line.fused_from) if isinstance(line.fused_from, list) else None,
    )


def build_line_item_responses(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> list[LineItemResponse]:
    parent = resolve_parent_ledger(invoice, config)
    return [build_line_item_response(line, parent_ledger=parent) for line in invoice.line_items]


def _is_team_expense_invoice(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """True for Team Expenses route / employee_claim DTs (skip line sub-ledger LLM)."""
    from app.services.classification.document_type_catalog import (
        ROUTE_TEAM,
        get_document_type_definition,
        is_team_expenses_document_type,
    )

    if (getattr(invoice, "route_target", None) or "").strip() == ROUTE_TEAM:
        return True
    defn = get_document_type_definition(
        getattr(invoice, "document_type_code", None) or "",
        document_types=list(config.document_types),
    )
    return is_team_expenses_document_type(defn)


def line_gl_mapping_applicable(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    if not gl_posting_applicable_for_invoice(
        invoice,
        document_types=list(config.document_types),
    ):
        return False
    if _is_team_expense_invoice(invoice, config):
        return False
    return bool(resolve_parent_ledger(invoice, config))


def line_sub_ledger_gate_applies(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    """True when blank line sub-ledgers must block posting (parent has catalogue)."""
    if not line_gl_mapping_applicable(invoice, config):
        return False
    if not getattr(invoice, "line_items", None):
        return False
    parent = resolve_parent_ledger(invoice, config)
    if not parent:
        return False
    from app.services.extraction.llm_coa_catalogue import (
        parent_ledger_has_sub_ledger_catalogue,
    )

    return parent_ledger_has_sub_ledger_catalogue(parent, config.chart_of_accounts)


def missing_line_sub_ledger_indexes(invoice: Invoice) -> list[int]:
    return [
        index
        for index, line in enumerate(getattr(invoice, "line_items", None) or [])
        if not (getattr(line, "sub_ledger", None) or "").strip()
    ]


def line_sub_ledger_review_required(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    if not line_sub_ledger_gate_applies(invoice, config):
        return False
    return bool(missing_line_sub_ledger_indexes(invoice))


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
