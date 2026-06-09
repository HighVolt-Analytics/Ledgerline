"""Persist rule book routing evaluation on invoices."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.master_data_service import create_pending_vendor, list_pending_vendors
from app.services.rule_book_config_io import load_rule_book_config_dict
from app.services.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_book_mapper import (
    FALLBACK_RULE_TYPE,
    load_classification_config,
    map_invoice_with_details,
)
from app.services.rule_engine import (
    doc_to_sample_email,
    detect_vendor,
    match_email_capture_rule,
    match_expense_rule,
    match_purchase_rule,
    match_team_expense_rule,
)
from app.schemas.master_data import PendingVendorCreate
from app.schemas.rule_book_config import validate_rule_book_config_payload

ROUTE_PURCHASE = "Purchase Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"

EVAL_AUTO_CODED = "auto_coded"
EVAL_NEEDS_REVIEW = "needs_review"
EVAL_PENDING_VENDOR = "pending_vendor"


@dataclass(frozen=True)
class InvoiceEvaluationResult:
    route_target: str | None
    matched_rule_ids: list[str]
    vendor_confidence: float
    evaluation_status: str


def _invoice_amount(invoice: Invoice) -> float | None:
    if invoice.total is None:
        return None
    return float(invoice.total)


def evaluate_invoice_routing(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    mapping_rule_type: str | None = None,
) -> InvoiceEvaluationResult:
    """Evaluate email route, vendor detection, and category rules for one invoice."""
    doc = invoice_to_eval_document(invoice)
    email = doc_to_sample_email(doc, default_mailbox="accounts@acme-hospitality.com.au")
    email_rule = match_email_capture_rule(email, config.email_capture_rules)
    vendor_match = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
    purchase = match_purchase_rule(doc, config.purchase_rules)
    expense = match_expense_rule(doc, config.expense_rules)
    team = match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=_invoice_amount(invoice),
    )

    matched_rule_ids: list[str] = []
    if email_rule:
        matched_rule_ids.append(f"email:{email_rule.id}")
    if vendor_match.vendor:
        matched_rule_ids.append(f"vendor:{vendor_match.vendor.id}")
    if purchase:
        matched_rule_ids.append(f"purchase:{purchase.id}")
    elif expense:
        matched_rule_ids.append(f"expense:{expense.id}")
    elif team:
        matched_rule_ids.append(f"team:{team.id}")

    route_target: str | None = None
    if email_rule:
        route_target = email_rule.action.route_to
    elif purchase:
        route_target = ROUTE_PURCHASE
    elif team:
        route_target = ROUTE_TEAM
    elif expense:
        route_target = ROUTE_EXPENSES
    elif doc.po:
        route_target = ROUTE_PURCHASE

    threshold = config.vendor_detection_config.threshold
    confidence = vendor_match.confidence
    is_fallback = mapping_rule_type == FALLBACK_RULE_TYPE

    if confidence < threshold and not vendor_match.vendor:
        evaluation_status = EVAL_PENDING_VENDOR
    elif is_fallback or confidence < threshold:
        evaluation_status = EVAL_NEEDS_REVIEW
    elif purchase or expense or team or (
        vendor_match.vendor and vendor_match.vendor.default_ledger.strip()
    ):
        evaluation_status = EVAL_AUTO_CODED
    else:
        evaluation_status = EVAL_NEEDS_REVIEW

    return InvoiceEvaluationResult(
        route_target=route_target,
        matched_rule_ids=matched_rule_ids,
        vendor_confidence=confidence,
        evaluation_status=evaluation_status,
    )


def apply_evaluation_to_invoice(
    invoice: Invoice,
    result: InvoiceEvaluationResult,
) -> None:
    invoice.route_target = result.route_target
    invoice.matched_rule_ids = json.dumps(result.matched_rule_ids)
    invoice.vendor_confidence = result.vendor_confidence
    invoice.evaluation_status = result.evaluation_status


def parse_matched_rule_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(item) for item in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def apply_invoice_evaluation(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
    enqueue_pending: bool = True,
) -> InvoiceEvaluationResult:
    """Evaluate and persist routing fields; optionally enqueue unknown vendors."""
    if config is None:
        config = load_classification_config(invoice.org_id)

    existing_ids = parse_matched_rule_ids(invoice.matched_rule_ids)
    existing_email_ids = [rule_id for rule_id in existing_ids if rule_id.startswith("email:")]
    prior_route = invoice.route_target

    mapping_detail = map_invoice_with_details(invoice)
    result = evaluate_invoice_routing(
        invoice,
        config,
        mapping_rule_type=mapping_detail.rule_type,
    )

    if existing_email_ids and not any(
        rule_id.startswith("email:") for rule_id in result.matched_rule_ids
    ):
        merged_ids = existing_email_ids + result.matched_rule_ids
        result = InvoiceEvaluationResult(
            route_target=result.route_target or prior_route,
            matched_rule_ids=merged_ids,
            vendor_confidence=result.vendor_confidence,
            evaluation_status=result.evaluation_status,
        )

    apply_evaluation_to_invoice(invoice, result)

    if enqueue_pending and result.evaluation_status == EVAL_PENDING_VENDOR:
        await _maybe_enqueue_pending_vendor(session, invoice, result)

    await session.flush()
    return result


async def _maybe_enqueue_pending_vendor(
    session: AsyncSession,
    invoice: Invoice,
    result: InvoiceEvaluationResult,
) -> None:
    name = (invoice.vendor or "").strip()
    if not name:
        return

    existing = await list_pending_vendors(session, invoice.org_id)
    for row in existing:
        if row.detected_name.strip().lower() == name.lower():
            return

    await create_pending_vendor(
        session,
        invoice.org_id,
        PendingVendorCreate(
            detected_name=name,
            detected_abn=invoice.abn,
            source_invoice_id=invoice.id,
            confidence=result.vendor_confidence,
        ),
    )


def load_config_for_org(org_id: int) -> RuleBookConfigPayload:
    raw = load_rule_book_config_dict(org_id)
    return validate_rule_book_config_payload(raw)
