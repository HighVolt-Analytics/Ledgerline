"""Persist rule book routing evaluation on invoices."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.master_data.master_data_service import (
    classification_config_with_db_masters,
    create_pending_vendor,
    list_pending_vendors,
    list_vendor_masters,
)
from app.services.rule_book.rule_book_config_io import load_rule_book_config_with_masters
from app.services.rule_book.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_book.rule_book_mapper import (
    FALLBACK_RULE_TYPE,
    load_classification_config,
    map_invoice_with_details,
)
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.rule_book.rule_engine import (
    doc_to_sample_email,
    detect_customer,
    detect_vendor,
    match_email_capture_rule,
    match_expense_rule,
    match_purchase_rule,
    match_sales_rule,
    match_team_expense_rule,
)
from app.schemas.master_data import PendingVendorCreate
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.purchase.expense_vendor_policy import (
    EVAL_UNMATCHED_EXPENSE_VENDOR,
    customer_detection_evaluation_status,
    expense_vendor_hold_above,
    is_unmatched_expense_vendor_status,
    vendor_detection_evaluation_status,
)
from app.services.audit.audit_service import log_event
from app.services.ingest.capture_channel import infer_capture_channel
from app.services.classification.document_type_catalog import (
    DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN,
    min_route_confidence_for_document_type,
    route_target_for_document_type,
)

ROUTE_PURCHASE = "Purchase Management"
ROUTE_SALES = "Sales Management"
ROUTE_EXPENSES = "Expenses Management"
ROUTE_TEAM = "Team Expenses"
ROUTE_VAULT = "Vault"

EVAL_AUTO_CODED = "auto_coded"
EVAL_NEEDS_REVIEW = "needs_review"
EVAL_PENDING_APPROVAL = "pending_approval"
EVAL_AWAITING_CLASSIFICATION = "awaiting_classification"
EVAL_NEEDS_RESCAN = "needs_rescan"
EVAL_PENDING_VENDOR = "pending_vendor"


@dataclass(frozen=True)
class InvoiceEvaluationResult:
    route_target: str | None
    matched_rule_ids: list[str]
    vendor_confidence: float | None
    evaluation_status: str


def _invoice_amount(invoice: Invoice) -> float | None:
    if invoice.total is None:
        return None
    return float(invoice.total)


def _invoice_extracted_fields(invoice: Invoice) -> dict[str, str]:
    raw = invoice.extracted_fields
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v).strip() for k, v in raw.items() if str(v or "").strip()}


def _resolved_perspective(invoice: Invoice, config: RuleBookConfigPayload) -> str:
    from app.services.tenant.tenant_org_context import infer_perspective, org_context_from_config

    fields = _invoice_extracted_fields(invoice)
    stored = fields.get("perspective", "").strip().lower()
    llm_token = fields.get("llm_perspective", stored or "unknown").strip().lower()
    llm_perspective = llm_token if llm_token in {"purchase", "sales", "unknown"} else "unknown"
    org = org_context_from_config(config, None)
    return infer_perspective(
        org=org,
        seller_name=fields.get("seller_name", ""),
        seller_abn=fields.get("seller_abn", ""),
        buyer_name=fields.get("buyer_name", ""),
        buyer_abn=fields.get("buyer_abn", ""),
        llm_perspective=llm_perspective,
    )


def _should_route_sales_by_perspective(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> bool:
    from app.services.tenant.tenant_org_context import normalize_org_perspective, org_context_from_config

    org = org_context_from_config(config, None)
    default = normalize_org_perspective(org.default_perspective)
    if default not in {"seller", "mixed"}:
        return False
    return _resolved_perspective(invoice, config) == "sales"


def evaluate_invoice_routing(
    invoice: Invoice,
    config: RuleBookConfigPayload,
    *,
    mapping_rule_type: str | None = None,
    route_override: str | None = None,
    customer_masters: list | None = None,
) -> InvoiceEvaluationResult:
    """Evaluate email route, vendor/customer detection, and category rules for one invoice."""
    doc = invoice_to_eval_document(invoice)
    email = doc_to_sample_email(doc, default_mailbox="accounts@acme-hospitality.com.au")
    email_rule = match_email_capture_rule(email, config.email_capture_rules)
    threshold = config.vendor_detection_config.threshold
    purchase = match_purchase_rule(doc, config.purchase_rules)
    sales = match_sales_rule(doc, config.sales_rules)
    expense = match_expense_rule(doc, config.expense_rules)
    team = match_team_expense_rule(
        doc,
        config.team_expense_rules,
        amount=_invoice_amount(invoice),
    )

    matched_rule_ids: list[str] = []
    if email_rule:
        matched_rule_ids.append(f"email:{email_rule.id}")
    if sales:
        matched_rule_ids.append(f"sales:{sales.id}")
    elif purchase:
        matched_rule_ids.append(f"purchase:{purchase.id}")
    elif expense:
        matched_rule_ids.append(f"expense:{expense.id}")
    elif team:
        matched_rule_ids.append(f"team:{team.id}")

    route_target: str | None = None
    dt_code = (invoice.document_type_code or "").strip().upper()
    dt_confidence = float(invoice.document_type_confidence or 0.0)
    dt_route = (
        route_target_for_document_type(dt_code, config.document_types)
        if dt_code
        else None
    )
    dt_min_confidence = (
        min_route_confidence_for_document_type(dt_code, config.document_types)
        if dt_code
        else DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN
    )
    if dt_code and dt_confidence >= dt_min_confidence and dt_route:
        route_target = dt_route
        matched_rule_ids.append(f"dt:{dt_code}")
    elif email_rule:
        route_target = email_rule.action.route_to
    elif sales:
        route_target = ROUTE_SALES
    elif _should_route_sales_by_perspective(invoice, config):
        route_target = ROUTE_SALES
        matched_rule_ids.append("perspective:sales")
    elif purchase:
        route_target = ROUTE_PURCHASE
    elif expense:
        route_target = ROUTE_EXPENSES
    elif team:
        route_target = ROUTE_TEAM
    elif is_plausible_po_reference(doc.po):
        route_target = ROUTE_PURCHASE
    else:
        from app.services.purchase.purchase_document_service import infer_purchase_document_type

        if infer_purchase_document_type(invoice):
            route_target = ROUTE_PURCHASE

    is_fallback = mapping_rule_type == FALLBACK_RULE_TYPE

    from app.services.master_data.vendor_detection import (
        find_matching_customer_master,
        find_matching_vendor_master,
    )
    from app.services.master_data.vendor_registration_policy import (
        customer_registration_required,
        persisted_vendor_confidence,
        resolve_document_type_definition,
        vendor_registration_required,
    )

    dt_definition = resolve_document_type_definition(
        dt_code,
        document_types=config.document_types,
    )
    route_for_counterparty = (route_override or route_target or "").strip()
    is_sales_route = route_for_counterparty == ROUTE_SALES

    if is_sales_route:
        masters = customer_masters or []
        customer_match = detect_customer(
            doc,
            masters,
            config.vendor_detection_config,
        )
        confidence = customer_match.confidence
        known_master = find_matching_customer_master(doc.vendor, doc.abn, masters)
        registration_required = customer_registration_required(
            route_target=route_for_counterparty or route_target,
            document_type=dt_definition,
        )
        counterparty_flag = customer_detection_evaluation_status(
            confidence=confidence,
            threshold=threshold,
            known_master=known_master,
            registration_required=registration_required,
        )
        if customer_match.customer and confidence >= threshold:
            matched_rule_ids.append(f"customer:{customer_match.customer.id}")
    else:
        vendor_match = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
        confidence = vendor_match.confidence
        known_master = find_matching_vendor_master(doc.vendor, doc.abn, config.vendor_masters)
        registration_required = vendor_registration_required(
            route_target=route_for_counterparty or route_target,
            document_type=dt_definition,
            purchase_document_type=invoice.purchase_document_type,
        )
        counterparty_flag = vendor_detection_evaluation_status(
            route_target=route_for_counterparty or None,
            confidence=confidence,
            threshold=threshold,
            known_master=known_master,
            amount=_invoice_amount(invoice),
            hold_above=expense_vendor_hold_above(config),
            registration_required=registration_required,
        )
        if vendor_match.vendor and confidence >= threshold:
            matched_rule_ids.append(f"vendor:{vendor_match.vendor.id}")

    if counterparty_flag:
        evaluation_status = counterparty_flag
    elif dt_code and dt_confidence < dt_min_confidence:
        evaluation_status = EVAL_NEEDS_REVIEW
    elif is_fallback:
        evaluation_status = EVAL_NEEDS_REVIEW
    elif purchase or sales or expense or team or (
        "perspective:sales" in matched_rule_ids
    ) or (
        is_sales_route
        and customer_match.customer
        and customer_match.customer.default_ledger.strip()
    ) or (
        not is_sales_route
        and vendor_match.vendor
        and vendor_match.vendor.default_ledger.strip()
    ) or (known_master and known_master.default_ledger.strip()):
        evaluation_status = EVAL_AUTO_CODED
    else:
        evaluation_status = EVAL_NEEDS_REVIEW

    if is_sales_route:
        if known_master and f"customer:{known_master.id}" not in matched_rule_ids:
            matched_rule_ids.append(f"customer:{known_master.id}")
    elif known_master and f"vendor:{known_master.id}" not in matched_rule_ids:
        matched_rule_ids.append(f"vendor:{known_master.id}")

    return InvoiceEvaluationResult(
        route_target=route_target,
        matched_rule_ids=matched_rule_ids,
        vendor_confidence=persisted_vendor_confidence(
            confidence=confidence,
            registration_required=registration_required,
        ),
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
    if invoice.evaluation_status == EVAL_AWAITING_CLASSIFICATION:
        code = (invoice.document_type_code or "").strip().upper()
        if code:
            invoice.evaluation_status = None
    if config is None:
        config = await load_classification_config(session, invoice.tenant_id)
    config = await classification_config_with_db_masters(session, invoice.tenant_id, config)

    existing_ids = parse_matched_rule_ids(invoice.matched_rule_ids)
    existing_email_ids = [rule_id for rule_id in existing_ids if rule_id.startswith("email:")]
    prior_route = invoice.route_target
    dt_min_confidence = (
        min_route_confidence_for_document_type(
            (invoice.document_type_code or "").strip().upper(),
            config.document_types,
        )
        if (invoice.document_type_code or "").strip()
        else DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN
    )
    dt_confident = bool(
        (invoice.document_type_code or "").strip()
        and float(invoice.document_type_confidence or 0.0) >= dt_min_confidence
    )

    mapping_detail = map_invoice_with_details(invoice, config=config)
    from app.services.master_data.customer_master_service import list_customer_masters

    customer_masters = await list_customer_masters(session, invoice.tenant_id)
    result = evaluate_invoice_routing(
        invoice,
        config,
        mapping_rule_type=mapping_detail.rule_type,
        route_override=prior_route,
        customer_masters=customer_masters,
    )

    if (prior_route or "").strip() and not dt_confident:
        merged_ids = list(dict.fromkeys([*existing_ids, *result.matched_rule_ids]))
        # Ingest / email capture route is sticky; DT classification overrides when confident.
        evaluation_status = result.evaluation_status
        if prior_route.strip() == ROUTE_TEAM and evaluation_status == EVAL_PENDING_VENDOR:
            evaluation_status = EVAL_AUTO_CODED
        result = InvoiceEvaluationResult(
            route_target=prior_route,
            matched_rule_ids=merged_ids,
            vendor_confidence=result.vendor_confidence,
            evaluation_status=evaluation_status,
        )

    apply_evaluation_to_invoice(invoice, result)

    if result.evaluation_status == EVAL_PENDING_VENDOR:
        from app.services.master_data.vendor_hold_service import purchase_invoice_trusts_po_register

        if await purchase_invoice_trusts_po_register(session, invoice):
            invoice.evaluation_status = EVAL_AUTO_CODED

    if is_unmatched_expense_vendor_status(result.evaluation_status):
        await log_event(
            session,
            "unmatched_expense_vendor",
            invoice_id=invoice.id,
            detail={
                "vendor": invoice.vendor,
                "vendor_confidence": result.vendor_confidence,
                "amount": _invoice_amount(invoice),
                "threshold": config.vendor_detection_config.threshold,
                "hold_above": expense_vendor_hold_above(config),
            },
        )

    route = (prior_route or result.route_target or "").strip()
    threshold = config.vendor_detection_config.threshold
    if route == ROUTE_TEAM and (result.vendor_confidence or 0) < threshold:
        from app.services.purchase.team_expense_validator import resolve_employee_for_sender

        employee = await resolve_employee_for_sender(
            session,
            invoice.tenant_id,
            invoice.email_sender,
        )
        await log_event(
            session,
            "unmatched_team_vendor",
            invoice_id=invoice.id,
            detail={
                "vendor_name": invoice.vendor,
                "confidence_score": result.vendor_confidence,
                "employee_name": employee.name if employee else None,
                "channel": infer_capture_channel(invoice.email_sender),
            },
        )

    if enqueue_pending and invoice.evaluation_status == EVAL_PENDING_VENDOR:
        route = (invoice.route_target or "").strip()
        if route == ROUTE_SALES:
            await _maybe_enqueue_pending_customer(session, invoice, result, config=config)
        else:
            await _maybe_enqueue_pending_vendor(session, invoice, result, config=config)

    from app.services.purchase.purchase_match_service import sync_purchase_order_from_invoice

    await sync_purchase_order_from_invoice(session, invoice)

    await session.flush()
    return result


async def ensure_pending_vendor_queued(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
    confidence: float | None = None,
) -> bool:
    """Ensure a pending_vendors row exists for an invoice awaiting registration."""
    if config is None:
        config = await load_classification_config(session, invoice.tenant_id)

    from app.services.master_data.vendor_registration_policy import (
        resolve_document_type_definition,
        vendor_registration_required,
    )

    definition = resolve_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )
    if not vendor_registration_required(
        route_target=invoice.route_target,
        document_type=definition,
        purchase_document_type=invoice.purchase_document_type,
    ):
        return False

    name = (invoice.vendor or "").strip()
    if not name:
        return False

    from app.services.master_data.vendor_detection import find_matching_vendor_master

    db_masters = await list_vendor_masters(session, invoice.tenant_id)
    if find_matching_vendor_master(name, invoice.abn, db_masters):
        return False

    existing = await list_pending_vendors(session, invoice.tenant_id)
    for row in existing:
        if row.detected_name.strip().lower() == name.lower():
            return True

    try:
        await create_pending_vendor(
            session,
            invoice.tenant_id,
            PendingVendorCreate(
                detected_name=name,
                detected_abn=invoice.abn,
                source_invoice_id=invoice.id,
                confidence=confidence if confidence is not None else float(invoice.vendor_confidence or 0),
            ),
        )
        return True
    except ValueError:
        return False


async def ensure_pending_customer_queued(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
    confidence: float | None = None,
) -> bool:
    """Ensure a pending_customers row exists for a sales invoice awaiting registration."""
    if config is None:
        config = await load_classification_config(session, invoice.tenant_id)

    from app.services.master_data.vendor_registration_policy import (
        customer_registration_required,
        resolve_document_type_definition,
    )

    definition = resolve_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )
    if not customer_registration_required(
        route_target=invoice.route_target,
        document_type=definition,
    ):
        return False

    name = (invoice.vendor or "").strip()
    if not name:
        return False

    from app.services.master_data.customer_master_service import (
        create_pending_customer,
        list_customer_masters,
        list_pending_customers,
    )
    from app.services.master_data.vendor_detection import find_matching_customer_master

    db_masters = await list_customer_masters(session, invoice.tenant_id)
    if find_matching_customer_master(name, invoice.abn, db_masters):
        return False

    existing = await list_pending_customers(session, invoice.tenant_id)
    for row in existing:
        if row.detected_name.strip().lower() == name.lower():
            return True

    try:
        from app.schemas.master_data import PendingCustomerCreate

        await create_pending_customer(
            session,
            invoice.tenant_id,
            PendingCustomerCreate(
                detected_name=name,
                detected_abn=invoice.abn,
                source_invoice_id=invoice.id,
                confidence=confidence if confidence is not None else float(invoice.vendor_confidence or 0),
            ),
        )
        return True
    except ValueError:
        return False


async def _maybe_enqueue_pending_customer(
    session: AsyncSession,
    invoice: Invoice,
    result: InvoiceEvaluationResult,
    *,
    config: RuleBookConfigPayload | None = None,
) -> None:
    if invoice.evaluation_status != EVAL_PENDING_VENDOR:
        return
    await ensure_pending_customer_queued(
        session,
        invoice,
        config=config,
        confidence=result.vendor_confidence,
    )


async def _maybe_enqueue_pending_vendor(
    session: AsyncSession,
    invoice: Invoice,
    result: InvoiceEvaluationResult,
    *,
    config: RuleBookConfigPayload | None = None,
) -> None:
    if invoice.evaluation_status != EVAL_PENDING_VENDOR:
        return
    await ensure_pending_vendor_queued(
        session,
        invoice,
        config=config,
        confidence=result.vendor_confidence,
    )


async def load_config_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> RuleBookConfigPayload:
    return await load_classification_config(session, tenant_id)


async def load_posting_config_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> RuleBookConfigPayload:
    """Rule book for dossier/matrix reads — document types only, no vendor/employee masters."""
    from app.services.rule_book.rule_book_config_io import load_posting_config_payload

    return await load_posting_config_payload(session, tenant_id)
