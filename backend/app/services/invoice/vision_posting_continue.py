"""Continue understood-path posting when Rule Book DT allows it.

Vision type-suggest + DT map + DT-scoped extract (or legacy header extract) already
ran. This module decides whether to keep the vault-only early return or continue
validate → Approvals → resume posting without re-running OCR/full extract.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.audit.audit_detail_helpers import validation_audit_detail
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_approval_service import (
    apply_document_type_approval_gate,
)
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_playbook_profile_service import (
    allows_posting_pipeline,
)
from app.services.invoice.invoice_data import invoice_data_from_invoice
from app.services.invoice.invoice_evaluation_service import (
    EVAL_LINE_ITEMS_REVIEW,
    EVAL_VISION_HEADER_REVIEW,
    EVAL_VISION_VAULTED,
)
from app.services.shared.notifier import send_notification
from app.services.purchase.team_expense_validator import has_receipt_attachment
from app.services.rule_book.validator import all_passed, results_to_json, run_all_validations
from app.services.tenant.tenant_org_context import OrgContext

_VISION_EVAL_HOLD = frozenset({EVAL_VISION_VAULTED, EVAL_VISION_HEADER_REVIEW})


def vision_should_sync_register(definition: DocumentTypeDefinition | None) -> bool:
    """True when posting=No DT is a PO/GRN/SO/DN register document (not vault-only)."""
    if definition is None:
        return False
    from app.services.classification.document_type_playbook_service import (
        _infer_purchase_bundle_role,
        _infer_sales_bundle_role,
    )

    purchase_role = _infer_purchase_bundle_role(definition)
    sales_role = _infer_sales_bundle_role(definition)
    return purchase_role in {"po", "grn"} or sales_role in {"so", "dn"}


def vision_should_continue_posting(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
    *,
    header_ok: bool,
) -> bool:
    """True when understood path should enter validate→Approvals→journal."""
    if not header_ok:
        return False
    # Extract already set line_items_review when required lines were empty.
    if (invoice.evaluation_status or "").strip() == EVAL_LINE_ITEMS_REVIEW:
        return False
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return False
    if definition is None:
        return False
    return allows_posting_pipeline(definition)


def vision_dt_never_posts(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
) -> bool:
    """True when Rule Book policy blocks posting regardless of header quality."""
    if not (invoice.document_type_code or "").strip():
        return False
    if definition is None:
        return False
    return not allows_posting_pipeline(definition)


def vision_posting_skip_reason(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
    *,
    header_ok: bool,
) -> str:
    # DT policy is reported first: a posting=No document would be skipped even
    # with a perfect header, so header_not_ok is not the governing reason.
    if vision_dt_never_posts(invoice, definition):
        return "dt_not_posting"
    if (invoice.evaluation_status or "").strip() == EVAL_LINE_ITEMS_REVIEW:
        return "line_items_missing"
    if not header_ok:
        return "header_not_ok"
    if not (invoice.document_type_code or "").strip():
        return "no_document_type"
    if definition is None:
        return "definition_missing"
    return "continue"


def vision_hold_evaluation_status(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
    *,
    header_ok: bool,
) -> str:
    """Evaluation status for the vault-only exit of the understood path.

    Documents whose DT never posts (Air Waybill, packing list, etc.) have no
    payable amounts to reconcile, so an incomplete money header is expected and
    must not raise a header-review flag. They vault as complete instead.
    Header review stays for documents that were meant to post.
    """
    if vision_dt_never_posts(invoice, definition):
        return EVAL_VISION_VAULTED
    if (invoice.evaluation_status or "").strip() == EVAL_LINE_ITEMS_REVIEW:
        return EVAL_LINE_ITEMS_REVIEW
    return EVAL_VISION_VAULTED if header_ok else EVAL_VISION_HEADER_REVIEW


def _extracted_needs_review(invoice: Invoice) -> bool:
    fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
    token = fields.get("needs_review")
    if token is True:
        return True
    if isinstance(token, str) and token.strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def vision_header_ok_from_invoice(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
) -> bool:
    """Derive header_ok from persisted invoice state (for Approvals resume)."""
    from app.services.approval.approval_pipeline_service import payable_fields_complete
    from app.services.approval.approval_service import _assert_invoice_ready_for_approval
    from app.services.invoice.due_date_defaults import apply_due_on_receipt_to_invoice

    if _extracted_needs_review(invoice):
        return False
    # Only when DT playbook marks due_date compulsory and the print omitted it.
    apply_due_on_receipt_to_invoice(invoice, definition)
    if definition is not None and allows_posting_pipeline(definition):
        if not payable_fields_complete(invoice):
            return False
    try:
        _assert_invoice_ready_for_approval(invoice, definition=definition)
    except ValueError:
        return False
    return True


_VISION_POSTING_SKIP_MESSAGES: dict[str, str] = {
    "dt_not_posting": (
        "Supporting document — stored in vault only; posting is not applicable "
        "for this document type."
    ),
    "header_not_ok": (
        "Complete header fields in the Fields tab (vendor, amounts, dates), save, "
        "then confirm again."
    ),
    "no_document_type": "Confirm document type in the Fields tab before approving.",
    "definition_missing": "Document type is not in your Rule Book — fix DT before approving.",
}


def vision_posting_skip_user_message(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None,
    *,
    header_ok: bool,
) -> str:
    reason = vision_posting_skip_reason(invoice, definition, header_ok=header_ok)
    return _VISION_POSTING_SKIP_MESSAGES.get(
        reason,
        "Cannot confirm this document into the posting pipeline yet.",
    )


def resolve_vision_posting_definition(
    invoice: Invoice,
    config: RuleBookConfigPayload,
) -> DocumentTypeDefinition | None:
    code = (invoice.document_type_code or "").strip().upper()
    if not code:
        return None
    return get_document_type_definition(code, document_types=config.document_types)


def _apply_dt_route_target(invoice: Invoice, definition: DocumentTypeDefinition) -> None:
    from app.services.classification.document_type_catalog import (
        ROUTE_TEAM,
        is_team_expenses_document_type,
        resolved_route_for_definition,
    )

    route = resolved_route_for_definition(definition)
    if not route and is_team_expenses_document_type(definition):
        route = ROUTE_TEAM
    if route:
        invoice.route_target = route


def _clear_vision_eval_hold(invoice: Invoice) -> None:
    if (invoice.evaluation_status or "").strip() in _VISION_EVAL_HOLD:
        invoice.evaluation_status = None


async def continue_vision_understood_posting(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
    org: OrgContext,
    definition: DocumentTypeDefinition,
) -> None:
    """Validate → Approvals → resume mapping/journal using persisted vision fields."""
    # Lazy imports avoid circular import with pipeline → this module.
    from app.services.approval.approval_pipeline_service import (
        human_approval_may_bypass_validation,
        human_approved_payable_bypass,
    )
    from app.services.classification.document_type_catalog import (
        ROUTE_EXPENSES,
        ROUTE_TEAM,
        is_team_expenses_document_type,
        resolved_route_for_definition,
    )
    from app.services.invoice.pipeline import (
        _log_processing_override_skip,
        _sync_counterparty_and_evaluate,
        _vendor_hold_unless_skipped,
        prepare_route_register_before_posting,
        resume_invoice_posting_pipeline,
    )
    from app.services.invoice.processing_override_catalog import should_skip
    from app.services.purchase.team_expense_route_policy import (
        ensure_team_expenses_document_type,
        normalize_capture_source,
        should_force_team_expenses,
        team_expenses_allowed_capture,
    )
    from app.services.vault.vault_blob_sync import sync_invoice_blob_path

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    _apply_dt_route_target(loaded, definition)
    _clear_vision_eval_hold(loaded)
    invoice.route_target = loaded.route_target
    invoice.evaluation_status = loaded.evaluation_status

    parsed = invoice_data_from_invoice(loaded)
    bypass_review_gates = await human_approved_payable_bypass(session, loaded)

    await log_event(
        session,
        "vision_posting_continued",
        invoice_id=loaded.id,
        detail={
            "document_type_code": loaded.document_type_code,
            "route_target": loaded.route_target,
            "posting": definition.posting,
            "klass": definition.klass,
        },
    )

    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=config,
        org=org,
        force_dt_route=True,
    )
    # Team Expenses: employee-channel policy wins; upload never stays on TE.
    employees = list(config.employee_masters or [])
    capture_ok = team_expenses_allowed_capture(normalize_capture_source(loaded))
    if should_force_team_expenses(loaded, employees):
        ensure_team_expenses_document_type(loaded, config.document_types)
        loaded.route_target = ROUTE_TEAM
    elif not capture_ok and (
        (loaded.route_target or "").strip() == ROUTE_TEAM
        or is_team_expenses_document_type(definition)
    ):
        catalogue_route = resolved_route_for_definition(definition)
        if catalogue_route and catalogue_route != ROUTE_TEAM:
            loaded.route_target = catalogue_route
        else:
            loaded.route_target = ROUTE_EXPENSES
    elif is_team_expenses_document_type(definition) and capture_ok:
        team_route = resolved_route_for_definition(definition) or ROUTE_TEAM
        loaded.route_target = team_route
    else:
        catalogue_route = resolved_route_for_definition(definition)
        if catalogue_route and catalogue_route != ROUTE_TEAM:
            loaded.route_target = catalogue_route
        elif catalogue_route == ROUTE_TEAM and capture_ok:
            loaded.route_target = ROUTE_TEAM
    invoice.route_target = loaded.route_target
    invoice.document_type_code = loaded.document_type_code
    invoice.document_type_confidence = loaded.document_type_confidence
    invoice.evaluation_status = loaded.evaluation_status
    if (loaded.route_target or "").strip() == ROUTE_TEAM:
        from app.services.purchase.team_expense_kind_service import stamp_team_expense_kind
        from app.services.purchase.team_expense_service import (
            stamp_team_expense_employee_identity,
        )

        await stamp_team_expense_employee_identity(session, loaded)
        # No definition passed: ensure_team_expenses_document_type may have reassigned the DT.
        await stamp_team_expense_kind(session, loaded, config)
        invoice.team_expense_kind = loaded.team_expense_kind
    invoice.vendor = loaded.vendor

    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = loaded.evaluation_status
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.VALIDATING
    loaded.status = InvoiceStatus.VALIDATING
    await session.flush()

    results = await run_all_validations(
        parsed,
        session,
        loaded.id,
        tenant_id=loaded.tenant_id,
        sender=loaded.email_sender,
        route_target=loaded.route_target,
        purchase_document_type=loaded.purchase_document_type,
        has_receipt_file=has_receipt_attachment(loaded.raw_file_path),
        document_type_code=loaded.document_type_code,
        document_types=list(config.document_types),
        validation_profile=None,
        playbook_gates=None,
        invoice=loaded,
    )
    loaded.validation_results = results_to_json(results)
    invoice.validation_results = loaded.validation_results
    if parsed.abn:
        loaded.abn = parsed.abn
        invoice.abn = parsed.abn

    if not all_passed(results):
        if bypass_review_gates and human_approval_may_bypass_validation(results):
            await log_event(
                session,
                "validation_bypassed_after_human_approval",
                invoice_id=loaded.id,
                detail=validation_audit_detail(
                    results,
                    route_target=loaded.route_target,
                    has_receipt_file=has_receipt_attachment(loaded.raw_file_path),
                ),
            )
        elif should_skip(loaded, "validation"):
            await _log_processing_override_skip(session, loaded, "validation")
            await log_event(
                session,
                "validation_bypassed_processing_override",
                invoice_id=loaded.id,
                detail=validation_audit_detail(
                    results,
                    route_target=loaded.route_target,
                    has_receipt_file=has_receipt_attachment(loaded.raw_file_path),
                ),
            )
        else:
            await _sync_counterparty_and_evaluate(
                session,
                loaded,
                parsed=parsed,
                config=config,
                org=org,
            )
            await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
            invoice.raw_file_path = loaded.raw_file_path
            invoice.route_target = loaded.route_target
            if await _vendor_hold_unless_skipped(session, loaded):
                invoice.status = InvoiceStatus.EXCEPTION
                invoice.evaluation_status = loaded.evaluation_status
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return
            invoice.status = InvoiceStatus.EXCEPTION
            loaded.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "validation_failed",
                invoice_id=loaded.id,
                detail=validation_audit_detail(
                    results,
                    route_target=loaded.route_target,
                    has_receipt_file=has_receipt_attachment(loaded.raw_file_path),
                ),
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    await log_event(
        session,
        "validation_passed",
        invoice_id=loaded.id,
        detail=validation_audit_detail(
            results,
            route_target=loaded.route_target,
            has_receipt_file=has_receipt_attachment(loaded.raw_file_path),
        ),
    )

    # Register sync must run before the approval gate. Otherwise commercial
    # invoices held for match_not_clean never get sales/purchase_document_type
    # or SO/PO.invoice_id (classic OCR path syncs before validation/approval).
    invoice.status = loaded.status
    invoice.evaluation_status = loaded.evaluation_status
    invoice.route_target = loaded.route_target
    invoice.vendor = loaded.vendor
    invoice.raw_file_path = loaded.raw_file_path
    invoice.validation_results = loaded.validation_results
    invoice.document_type_code = loaded.document_type_code
    invoice.so_reference = loaded.so_reference
    invoice.po_reference = loaded.po_reference
    invoice.sales_document_type = loaded.sales_document_type
    invoice.purchase_document_type = loaded.purchase_document_type

    if await prepare_route_register_before_posting(
        session,
        invoice,
        bypass_review_gates=bypass_review_gates,
    ):
        return

    loaded.sales_document_type = invoice.sales_document_type
    loaded.purchase_document_type = invoice.purchase_document_type
    loaded.so_reference = invoice.so_reference
    loaded.po_reference = invoice.po_reference
    loaded.evaluation_status = invoice.evaluation_status
    loaded.status = invoice.status

    if await apply_document_type_approval_gate(
        session,
        loaded,
        definition=definition,
        validation_results=results,
        human_approval_bypass=bypass_review_gates,
    ):
        invoice.status = loaded.status
        invoice.evaluation_status = loaded.evaluation_status
        invoice.sales_document_type = loaded.sales_document_type
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.so_reference = loaded.so_reference
        invoice.po_reference = loaded.po_reference
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = loaded.status
    invoice.evaluation_status = loaded.evaluation_status
    invoice.route_target = loaded.route_target
    invoice.vendor = loaded.vendor
    invoice.raw_file_path = loaded.raw_file_path
    invoice.validation_results = loaded.validation_results
    invoice.document_type_code = loaded.document_type_code
    invoice.sales_document_type = loaded.sales_document_type
    invoice.purchase_document_type = loaded.purchase_document_type
    invoice.so_reference = loaded.so_reference
    invoice.po_reference = loaded.po_reference

    await resume_invoice_posting_pipeline(session, invoice, config=config)
