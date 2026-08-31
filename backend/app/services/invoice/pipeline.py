"""Run the invoice processing pipeline for one PDF."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import flag_enabled_for_dt, get_settings
from app.services.shared.amount_sanity import plausible_money, sanitize_parsed_line_item
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.journal import JournalEntry, JournalEntryKind
from app.models.line_item import LineItem
from app.models.vendor import VendorRegistry
from app.models.customer import CustomerRegistry
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.rule_book.account_mapper import (
    AccountMapping,
    MappingDetail,
    resolve_fallback_account_mapping,
)
from app.services.dossier.document_duplicate_service import (
    evaluate_file_hash_duplicate,
    find_existing_ingest_duplicate,
    find_invoice_by_file_hash,
    log_duplicate_skipped,
    resolve_ingest_duplicate,
)
from app.services.dossier.document_ref_service import (
    assign_document_ref,
    audit_document_detail,
    original_document_audit_fields,
)
from app.services.ingest.ingest_capture_service import (
    apply_ingest_capture,
    capture_rule_requires_employee_sender,
    evaluate_ingest_capture,
    log_ingest_capture_decision,
)
from app.services.approval.approval_pipeline_service import (
    human_approval_may_bypass_validation,
    human_approved_payable_bypass,
)
from app.services.ingest.ingest_fanout_service import IngestSourceMetadata, ingest_file_with_fanout
from app.services.invoice.processing_override_catalog import (
    clear_processing_overrides,
    override_bypasses_purchase_hold,
    override_bypasses_sales_hold,
    should_skip,
    skip_steps_for,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED as EVAL_STATUS_AUTO_CODED,
    EVAL_AWAITING_CLASSIFICATION,
    EVAL_LINE_GL_REVIEW,
    EVAL_LINE_ITEMS_REVIEW,
    EVAL_NEEDS_RESCAN,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_VENDOR,
    EVAL_VISION_HEADER_REVIEW,
    EVAL_VISION_VAULTED,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
    ROUTE_VAULT,
    apply_invoice_evaluation,
    load_config_for_tenant,
)
from app.services.invoice.routing_review_service import (
    requires_gl_mapping_review,
    requires_playbook_review,
)
from app.services.classification.classification_learning_service import (
    few_shot_examples_for_tenant,
    human_confirmed_document_type,
    resolve_vendor_learning_key,
)
from app.services.classification.classification_drift_service import (
    check_vendor_classification_drift,
    drift_audit_detail,
)
from app.services.extraction.di_extract_service import OcrFailed
from app.services.extraction.document_ai_provider import (
    DocumentAiProvider,
    extract_fields,
)
from app.services.invoice.invoice_pipeline_phases import (
    apply_recognition_mode_gate,
    backfill_llm_dt_from_policy,
    reconcile_llm_dt_with_heading,
    evaluate_confidence_gate,
    evaluate_field_confidence_gate,
    field_confidence_audit_detail,
    gate_audit_detail,
    phase_image_quality,
    phase_layout_readiness,
    phase_llm_classify,
    phase_ocr_quality_confirm,
    persist_llm_party_context,
    phase_file_validity,
    phase_ocr,
    phase_storage_verify,
    phase_vision_dt_extract,
    phase_vision_header_extract,
    phase_vision_type_suggest,
    phase_vision_understand,
)
from app.services.extraction.llm_document_service import (
    apply_document_type_to_invoice,
    llm_result_to_invoice_data,
)
from app.schemas.classification_decision import ReviewReason
from app.services.tenant.tenant_org_context import ai_classification_from_config
from app.schemas.llm_document import LlmDocumentResult
from app.services.tenant.tenant_org_context import org_context_from_config
from app.services.vault.vault_paths import filename_from_stored
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_playbook_service import (
    evaluate_playbook_gates,
    resolve_definition_for_invoice,
)
from app.services.classification.document_type_approval_service import apply_document_type_approval_gate
from app.services.classification.document_type_playbook_profile_service import playbook_policy_audit_detail
from app.services.rule_book.rule_book_mapper import is_fallback_mapping, map_invoice_with_details
from app.services.purchase.team_expense_approval import apply_team_expense_approval_gate
from app.services.purchase.team_expense_service import record_team_expense_processed
from app.services.purchase.team_expense_validator import has_receipt_attachment
from app.services.master_data.vendor_hold_service import apply_vendor_hold_if_needed
from app.services.master_data.bundle_vendor_service import reconcile_dossier_vendor, resolve_canonical_vendor_name
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name
from app.services.invoice.invoice_amounts import backfill_invoice_amounts_from_sources
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem, invoice_data_from_invoice
from app.tenant_child_tables import journal_entries_for_invoice, line_items_for_invoice
from app.services.ingest.attachment_filter import filter_invoice_attachments
from app.services.audit.audit_detail_helpers import validation_audit_detail
from app.services.audit.audit_service import log_event
from app.utils.logger import get_logger
from app.services.ingest.capture_channel import infer_capture_channel, is_staff_claim_sender
from app.services.ingest.email_ingestion import RawEmail, mark_message_read
from app.services.shared.file_storage import open_pdf_for_reading
from app.services.vault.vault_blob_sync import (
    sync_invoice_blob_path,
    sync_vision_header_vault_path,
)
from app.services.ingest.graph_mail_folders import folder_moves_enabled
from app.services.payments.journal_generator import (
    generate_entries,
    get_unresolved_control_accounts,
    is_balanced,
)
from app.services.payments.journal_persist_service import persist_journal_lines
from app.services.payments.fiscal_period_service import PeriodClosedError
from app.services.master_data.journal_counterparty_resolver import (
    resolve_counterparty_registry_ids_for_journal,
)
from app.services.shared.notifier import send_notification
from app.services.reconciliation.reconciliation_service import reconcile_daily, save_reconciliation
from app.services.invoice.invoice_accrual_date import (
    effective_invoice_recon_date,
    halt_if_missing_accrual_date,
)
from app.services.reconciliation.stranded_journal_remediation import (
    purge_accrual_journals_for_invoice,
)
from app.services.rule_book.validator import all_passed, results_to_json, run_all_validations
from app.services.master_data.vendor_resolver import (
    UNKNOWN_SLUG,
    is_valid_storage_slug,
    resolve_storage_slug_for_parsed_vendor,
)
from app.services.master_data.customer_resolver import resolve_capture_slug
from app.utils.hashing import compute_sha256_bytes


async def _log_processing_override_skip(
    session: AsyncSession,
    invoice: Invoice,
    step_id: str,
) -> None:
    await log_event(
        session,
        "pipeline_step_skipped",
        invoice_id=invoice.id,
        detail={"step_id": step_id, "source": "processing_override"},
    )


def _counterparty_registration_pending(invoice: Invoice) -> bool:
    """True when evaluation already flagged unknown vendor/customer registration."""
    return (invoice.evaluation_status or "").strip() == EVAL_PENDING_VENDOR


async def _vendor_hold_unless_skipped(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    if should_skip(invoice, "vendor_registration"):
        await _log_processing_override_skip(session, invoice, "vendor_registration")
        return False
    return await apply_vendor_hold_if_needed(session, invoice)


def _finalize_vendor_counterparty(
    invoice: Invoice,
    *,
    parsed: object | None,
    config: object,
) -> None:
    """Canonicalize AP vendor name on invoice.vendor after counterparty sync."""
    from app.services.extraction.extraction_field_values import extracted_fields_from_invoice
    from app.services.sales.counterparty_service import resolve_counterparty_side

    fields = extracted_fields_from_invoice(invoice)
    side = resolve_counterparty_side(
        route_target=invoice.route_target,
        perspective=fields.get("perspective") or fields.get("llm_perspective"),
    )
    if side != "vendor" or not invoice.vendor:
        return

    parsed_abn = getattr(parsed, "abn", None) if parsed is not None else invoice.abn
    canonical = resolve_canonical_vendor_name(
        invoice.tenant_id,
        vendor_names=[invoice.vendor],
        abns=[parsed_abn],
        config=config,
    )
    if canonical:
        invoice.vendor = canonical
    elif not is_plausible_vendor_name(invoice.vendor):
        invoice.vendor = None


async def _sync_counterparty_and_evaluate(
    session: AsyncSession,
    invoice: Invoice,
    *,
    parsed: object | None,
    config: object,
    org: object,
    force_dt_route: bool = False,
) -> None:
    """Sync finance counterparty on invoice.vendor, then evaluate routing/match."""
    from app.services.sales.counterparty_service import sync_invoice_counterparty

    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)
    await apply_invoice_evaluation(
        session, invoice, config=config, force_dt_route=force_dt_route
    )
    prior_vendor = invoice.vendor
    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)
    if (invoice.vendor or "") != (prior_vendor or ""):
        await apply_invoice_evaluation(
            session, invoice, config=config, force_dt_route=force_dt_route
        )


async def _sync_and_evaluate_invoice(
    session: AsyncSession,
    invoice: Invoice,
    *,
    parsed: object | None = None,
    config: object | None = None,
    org: object | None = None,
) -> None:
    """Load pipeline context when needed, then sync counterparty and evaluate."""
    if config is None:
        config = await load_config_for_tenant(session, invoice.tenant_id)
    if org is None:
        tenant_row = await session.get(Tenant, invoice.tenant_id)
        org = org_context_from_config(config, tenant_row)
    if parsed is None:
        from app.services.invoice.invoice_data import invoice_data_from_invoice

        parsed = invoice_data_from_invoice(invoice)
    await _sync_counterparty_and_evaluate(
        session,
        invoice,
        parsed=parsed,
        config=config,
        org=org,
    )


async def _clear_purchase_awaiting_po_if_overridden(
    session: AsyncSession,
    invoice: Invoice,
    loaded: Invoice,
) -> None:
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

    if not override_bypasses_purchase_hold(invoice):
        return
    if loaded.evaluation_status != EVAL_AWAITING_PO:
        return
    await _log_processing_override_skip(session, invoice, "playbook")
    loaded.evaluation_status = EVAL_AUTO_CODED
    loaded.status = InvoiceStatus.PARSING
    invoice.evaluation_status = EVAL_AUTO_CODED
    invoice.status = InvoiceStatus.PARSING
    await session.flush()


async def _clear_sales_awaiting_so_if_overridden(
    session: AsyncSession,
    invoice: Invoice,
    loaded: Invoice,
) -> None:
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO

    if not override_bypasses_sales_hold(invoice):
        return
    if loaded.evaluation_status != EVAL_AWAITING_SO:
        return
    await _log_processing_override_skip(session, invoice, "playbook")
    loaded.evaluation_status = EVAL_AUTO_CODED
    loaded.status = InvoiceStatus.PARSING
    invoice.evaluation_status = EVAL_AUTO_CODED
    invoice.status = InvoiceStatus.PARSING
    await session.flush()


async def _dt_match_mode_requires_po(session: AsyncSession, invoice: Invoice) -> bool:
    """Whether the invoice document type's match policy requires PO linkage."""
    from app.services.classification.document_type_match_service import resolve_match_mode
    from app.services.classification.document_type_playbook_profile_service import (
        match_mode_requires_po,
    )
    from app.services.rule_book.rule_book_mapper import load_classification_config

    code = (invoice.document_type_code or "").strip()
    if not code:
        # Conservative default matches resolve_match_mode (three_way_po_grn).
        return True
    config = await load_classification_config(session, invoice.tenant_id)
    match_mode = resolve_match_mode(
        document_type_code=code,
        document_types=list(config.document_types),
        tenant_id=invoice.tenant_id,
    )
    return match_mode_requires_po(match_mode)


async def _dt_match_mode_requires_sales(session: AsyncSession, invoice: Invoice) -> bool:
    """Whether the invoice document type's match policy requires SO linkage."""
    from app.services.classification.document_type_match_service import resolve_match_mode
    from app.services.classification.document_type_playbook_profile_service import (
        match_mode_requires_sales,
    )
    from app.services.rule_book.rule_book_mapper import load_classification_config

    code = (invoice.document_type_code or "").strip()
    if not code:
        return True
    config = await load_classification_config(session, invoice.tenant_id)
    match_mode = resolve_match_mode(
        document_type_code=code,
        document_types=list(config.document_types),
        tenant_id=invoice.tenant_id,
    )
    return match_mode_requires_sales(match_mode)


async def _halt_or_bypass_purchase_awaiting_po(
    session: AsyncSession,
    invoice: Invoice,
    *,
    bypass_review_gates: bool,
    playbook_bypasses_po_hold: bool,
) -> bool:
    """After final ``sync_purchase_document``: hold or clear awaiting-PO.

    ``sync_purchase_document`` sets ``EXCEPTION`` + ``awaiting_po`` when the PO
    is missing. Callers that already marked the invoice ``PROCESSED`` must
    either stop here or restore ``PROCESSED`` before ledger publish.

    Returns True when the caller must return (held on awaiting PO).
    """
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

    awaiting = invoice.evaluation_status == EVAL_AWAITING_PO
    # Only purchase sync runs between _mark_invoice_processed and here, so an
    # EXCEPTION status means missing-PO hold even if evaluation_status was
    # cleared by an earlier bypass path.
    missing_po_exception = invoice.status == InvoiceStatus.EXCEPTION
    if not awaiting and not missing_po_exception:
        return False
    # Non-PO DTs must never stay on awaiting_po (stale hold / older sync path).
    match_requires_po = await _dt_match_mode_requires_po(session, invoice)
    if bypass_review_gates or playbook_bypasses_po_hold or not match_requires_po:
        if playbook_bypasses_po_hold and not bypass_review_gates and match_requires_po:
            await _log_processing_override_skip(session, invoice, "playbook")
        invoice.evaluation_status = EVAL_AUTO_CODED
        # Missing-PO sync flips status to EXCEPTION; restore PROCESSED so
        # publish_invoice_to_ledger does not raise after a deliberate bypass.
        invoice.status = InvoiceStatus.PROCESSED
        await session.flush()
        return False
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_PO
    await session.flush()
    await _purge_accruals_after_incomplete_halt(
        session, invoice, reason="awaiting_po_hold"
    )
    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def _halt_or_bypass_sales_awaiting_so(
    session: AsyncSession,
    invoice: Invoice,
    *,
    bypass_review_gates: bool,
    playbook_bypasses_so_hold: bool,
) -> bool:
    """After final ``sync_sales_document``: hold or clear awaiting-SO.

    ``sync_sales_document`` sets ``EXCEPTION`` + ``awaiting_so`` when the SO
    is missing. Callers that already marked the invoice ``PROCESSED`` must
    either stop here or restore ``PROCESSED`` before ledger publish.

    Returns True when the caller must return (held on awaiting SO).
    """
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED, ROUTE_SALES
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO

    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return False

    awaiting = invoice.evaluation_status == EVAL_AWAITING_SO
    if not awaiting:
        return False
    match_requires_so = await _dt_match_mode_requires_sales(session, invoice)
    if bypass_review_gates or playbook_bypasses_so_hold or not match_requires_so:
        if playbook_bypasses_so_hold and not bypass_review_gates and match_requires_so:
            await _log_processing_override_skip(session, invoice, "playbook")
        invoice.evaluation_status = EVAL_AUTO_CODED
        invoice.status = InvoiceStatus.PROCESSED
        await session.flush()
        return False
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_SO
    await session.flush()
    await _purge_accruals_after_incomplete_halt(
        session, invoice, reason="awaiting_so_hold"
    )
    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def _stop_if_not_processed_for_publish(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Belt-and-suspenders: never auto-publish a non-PROCESSED invoice."""
    if invoice.status == InvoiceStatus.PROCESSED:
        return False
    if invoice.status != InvoiceStatus.EXCEPTION:
        invoice.status = InvoiceStatus.EXCEPTION
    await session.flush()
    await _purge_accruals_after_incomplete_halt(
        session, invoice, reason="not_processed_for_publish"
    )
    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def _purge_accruals_after_incomplete_halt(
    session: AsyncSession,
    invoice: Invoice,
    *,
    reason: str,
) -> None:
    """Drop accrual journals when an invoice halts after journaling.

    Prevents stranded accruals (e.g. awaiting_po after journal write) from
    remaining on the day ledger. Payment/collection settlements are kept.
    """
    await purge_accrual_journals_for_invoice(
        session,
        invoice,
        reason=reason,
    )


def _mark_invoice_processed(invoice: Invoice) -> None:
    clear_processing_overrides(invoice)
    invoice.status = InvoiceStatus.PROCESSED
    # Invariant: PROCESSED ⇒ coding review is closed. All blocking gates
    # (validation, mapping review, vendor hold, variance, journal balance,
    # reconciliation) run before this point; a surviving needs_review is a
    # stale coding flag, not an open control hold. Vault / non-posting
    # finishers already normalize the same way.
    if (invoice.evaluation_status or "").strip() == EVAL_NEEDS_REVIEW:
        invoice.evaluation_status = EVAL_STATUS_AUTO_CODED


async def _mark_deterministic_mapping_auto_coded(
    session: AsyncSession,
    invoice: Invoice,
    loaded: Invoice,
    mapping_detail: MappingDetail,
) -> bool:
    """Close coding review after a deterministic Rule Book GL mapping.

    ``needs_review`` is a coding-state flag, not a posting-state flag. Once a
    non-fallback mapping has resolved a real GL account and all earlier review
    gates have passed, leaving it set makes a successfully posted invoice look
    operationally unresolved. Other control holds (vendor, approval, PO/SO)
    are deliberately not overridden.
    """
    current = (loaded.evaluation_status or invoice.evaluation_status or "").strip()
    if current != EVAL_NEEDS_REVIEW or is_fallback_mapping(mapping_detail):
        return False
    if not (mapping_detail.account_code or "").strip():
        return False

    loaded.evaluation_status = EVAL_STATUS_AUTO_CODED
    invoice.evaluation_status = EVAL_STATUS_AUTO_CODED
    await log_event(
        session,
        "evaluation_auto_coded",
        invoice_id=invoice.id,
        detail={
            "reason": "deterministic_gl_mapping",
            "document_type_code": loaded.document_type_code or invoice.document_type_code,
            "account_code": mapping_detail.account_code,
            "account_name": mapping_detail.account_name,
            "rule_type": mapping_detail.rule_type,
            "match_reason": mapping_detail.match_reason,
        },
    )
    return True


@dataclass
class EmailIngestResult:
    ingested_count: int = 0
    message_ids: list[str] = field(default_factory=list)
    preskip_exceptions: dict[str, str] = field(default_factory=dict)
    # message_id → mailbox email (needed for Graph folder moves on preskips)
    message_mailbox_emails: dict[str, str] = field(default_factory=dict)
    # stable message_id → Graph REST id for move/mark API calls
    message_graph_ids: dict[str, str] = field(default_factory=dict)


logger = get_logger(__name__)


def _filename_from_stored(stored: str, invoice_id: int, file_hash: str) -> str:
    _ = (invoice_id, file_hash)
    return filename_from_stored(stored)


def _scalar_field_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _apply_parsed_scalar(invoice: Invoice, field: str, value: object) -> None:
    if not _scalar_field_empty(getattr(invoice, field)):
        return
    setattr(invoice, field, value)


async def _hold_for_missing_line_sub_ledgers(
    session: AsyncSession,
    invoice: Invoice,
    loaded: Invoice,
    config,
    *,
    bypass_review_gates: bool,
) -> bool:
    """Hold posting when parent has a sub-ledger catalogue and any line is blank."""
    if bypass_review_gates or should_skip(invoice, "line_gl_mapping"):
        return False
    from app.services.invoice.line_item_gl_service import (
        line_sub_ledger_review_required,
        missing_line_sub_ledger_indexes,
        resolve_parent_ledger,
    )

    if not line_sub_ledger_review_required(loaded, config):
        return False
    missing = missing_line_sub_ledger_indexes(loaded)
    parent = resolve_parent_ledger(loaded, config)
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_LINE_GL_REVIEW
    loaded.status = InvoiceStatus.EXCEPTION
    loaded.evaluation_status = EVAL_LINE_GL_REVIEW
    await log_event(
        session,
        "line_gl_review_required",
        invoice_id=invoice.id,
        detail={
            "reason": "missing_line_sub_ledger",
            "parent_ledger": parent,
            "missing_line_indexes": missing,
            "missing_count": len(missing),
        },
    )
    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def _invoice_has_persisted_line_items(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """True when line_item rows exist — never lazy-load the collection.

    After ``clear_stale_not_understood_for_understood_path`` the relationship is
    expired. Touching ``invoice.line_items`` in async raises MissingGreenlet and
    poisons the session (PendingRollbackError on the next flush).
    """
    try:
        if "line_items" not in sa_inspect(invoice).unloaded:
            return bool(invoice.line_items)
    except Exception:
        pass
    count = (
        await session.execute(
            select(func.count())
            .select_from(LineItem)
            .where(*line_items_for_invoice(invoice.tenant_id, invoice.id))
        )
    ).scalar_one()
    return int(count or 0) > 0


async def _replace_line_items(
    session: AsyncSession,
    invoice: Invoice,
    lines: list[ParsedLineItem],
    *,
    trace: object | None = None,
) -> None:
    # Always delete via SQL — never lazy-load invoice.line_items (MissingGreenlet
    # after clear_stale expires the collection on the async understood path).
    await session.execute(
        delete(LineItem).where(
            *line_items_for_invoice(invoice.tenant_id, invoice.id),
        )
    )
    session.expire(invoice, ["line_items"])
    await session.flush()
    await session.refresh(invoice, attribute_names=["line_items"])
    from app.services.extraction.line_item_trace import row_key_for_item

    for index, line in enumerate(lines):
        row_key = row_key_for_item(line, index)
        cleaned = sanitize_parsed_line_item(line, trace=trace, row_key=row_key)
        if trace is not None:
            trace.record(row_key, "persist", "kept", "persisted_row")
        invoice.line_items.append(
            LineItem(
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                description=cleaned.description,
                qty=cleaned.qty,
                unit_price=cleaned.unit_price,
                amount=cleaned.amount,
                tax_amount=cleaned.tax_amount,
                extraction_source=cleaned.source,
                source_confidence=cleaned.source_confidence,
                fused_from=list(cleaned.fused_from) if cleaned.fused_from else None,
            )
        )
    await session.flush()


def _resolve_header_mapping(
    invoice: Invoice,
    *,
    config,
    purchase_order=None,
    sales_order=None,
) -> tuple[AccountMapping, MappingDetail]:
    """Map invoice header using unified classification config."""
    if not invoice.line_items:
        detail = map_invoice_with_details(
            invoice,
            config=config,
            purchase_order=purchase_order,
            sales_order=sales_order,
        )
        return (
            AccountMapping(
                account_code=detail.account_code,
                account_name=detail.account_name,
                expense_category=detail.expense_category,
            ),
            detail,
        )
    best_detail = map_invoice_with_details(
        invoice,
        config=config,
        purchase_order=purchase_order,
        sales_order=sales_order,
    )
    best = AccountMapping(
        account_code=best_detail.account_code,
        account_name=best_detail.account_name,
        expense_category=best_detail.expense_category,
    )
    for line in invoice.line_items:
        detail = map_invoice_with_details(
            invoice,
            config=config,
            line_description=line.description,
            purchase_order=purchase_order,
            sales_order=sales_order,
        )
        if not is_fallback_mapping(detail):
            return (
                AccountMapping(
                    account_code=detail.account_code,
                    account_name=detail.account_name,
                    expense_category=detail.expense_category,
                ),
                detail,
            )
    return best, best_detail


async def find_by_hash(
    session: AsyncSession,
    file_hash: str,
    *,
    tenant_id: int,
) -> Invoice | None:
    """Backward-compatible alias for file-hash lookup."""
    return await find_invoice_by_file_hash(session, file_hash, tenant_id=tenant_id)


async def _tenant_slug(session: AsyncSession, tenant_id: int) -> str:
    org = await session.get(Tenant, tenant_id)
    if org:
        return org.slug
    return get_settings().default_tenant_slug


async def _post_parse_relocate(
    session: AsyncSession,
    invoice: Invoice,
    parsed_vendor: str | None,
) -> None:
    await sync_invoice_blob_path(session, invoice, parsed_vendor=parsed_vendor)


async def _safe_auto_learn(session: AsyncSession, invoice: Invoice) -> None:
    """Post-process sender learning must not fail an otherwise successful pipeline."""
    try:
        await _auto_learn_sender(session, invoice)
        await _auto_learn_customer_sender(session, invoice)
    except Exception as exc:
        from app.utils.logger import get_logger

        get_logger(__name__).warning(
            "auto_learn_failed",
            invoice_id=invoice.id,
            error=str(exc),
        )


async def _auto_learn_sender(session: AsyncSession, invoice: Invoice) -> None:
    settings = get_settings()
    if not settings.blob_auto_learn_sender:
        return
    if not invoice.email_sender or not invoice.storage_vendor_slug:
        return
    if invoice.storage_vendor_slug == UNKNOWN_SLUG:
        return

    rows = (
        await session.execute(
            select(VendorRegistry).where(VendorRegistry.tenant_id == invoice.tenant_id)
        )
    ).scalars().all()
    for row in rows:
        if row.sender_pattern.lower() == invoice.email_sender.lower():
            return
        if row.vendor_slug == invoice.storage_vendor_slug:
            return

    session.add(
        VendorRegistry(
            tenant_id=invoice.tenant_id,
            vendor_slug=invoice.storage_vendor_slug,
            vendor_name=invoice.vendor or invoice.storage_vendor_slug,
            sender_pattern=invoice.email_sender,
            abn=invoice.abn,
            approved=False,
        )
    )
    await log_event(
        session,
        "vendor_sender_learned",
        invoice_id=invoice.id,
        detail={
            "sender": invoice.email_sender,
            "vendor_slug": invoice.storage_vendor_slug,
        },
    )


async def _auto_learn_customer_sender(session: AsyncSession, invoice: Invoice) -> None:
    settings = get_settings()
    if not settings.blob_auto_learn_sender:
        return
    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return
    if not invoice.email_sender or not invoice.storage_vendor_slug:
        return
    if invoice.storage_vendor_slug == UNKNOWN_SLUG:
        return

    rows = (
        await session.execute(
            select(CustomerRegistry).where(CustomerRegistry.tenant_id == invoice.tenant_id)
        )
    ).scalars().all()
    for row in rows:
        if row.sender_pattern.lower() == invoice.email_sender.lower():
            return
        if row.customer_slug == invoice.storage_vendor_slug:
            return

    session.add(
        CustomerRegistry(
            tenant_id=invoice.tenant_id,
            customer_slug=invoice.storage_vendor_slug,
            customer_name=invoice.vendor or invoice.storage_vendor_slug,
            sender_pattern=invoice.email_sender,
            abn=invoice.abn,
            approved=False,
        )
    )
    await log_event(
        session,
        "customer_sender_learned",
        invoice_id=invoice.id,
        detail={
            "sender": invoice.email_sender,
            "customer_slug": invoice.storage_vendor_slug,
        },
    )


def _finish_email_message(
    message_id: str,
    mailbox_email: str,
    *,
    access_token: str | None = None,
) -> None:
    """Mark read when folder moves are disabled (legacy behaviour)."""
    if not folder_moves_enabled():
        mark_message_read(message_id, mailbox_email, access_token=access_token)


def _maybe_finish_email_message(
    email: RawEmail,
    *,
    mark_processed: bool,
    mark_processed_only_if_ingested: bool,
    ingested_before: int,
    ingested_after: int,
    force: bool = False,
) -> None:
    if not mark_processed:
        return
    if (
        not force
        and mark_processed_only_if_ingested
        and ingested_after <= ingested_before
    ):
        return
    _finish_email_message(
        email.api_message_id,
        email.mailbox_email,
        access_token=email.graph_access_token,
    )


async def ingest_email_attachments(
    session: AsyncSession,
    emails: list[RawEmail],
    *,
    tenant_id: int,
    tenant_slug: str,
    connected_mailbox_id: int | None = None,
    mark_processed: bool = True,
    mark_processed_only_if_ingested: bool = False,
    known_message_ids: frozenset[str] | None = None,
) -> EmailIngestResult:
    """Save invoice attachments (PDF/image/DOCX) from emails."""
    result = EmailIngestResult()
    org = await session.get(Tenant, tenant_id)
    tenant_name = org.name if org else None

    capture_config = await load_config_for_tenant(session, tenant_id)
    enabled_capture_rules = [r for r in capture_config.email_capture_rules if r.enabled]
    logger.info(
        "email_ingest_batch_started",
        tenant_id=str(tenant_id),
        connected_mailbox_id=connected_mailbox_id,
        email_count=len(emails),
        enabled_capture_rule_count=len(enabled_capture_rules),
        known_message_id_count=len(known_message_ids or ()),
        mark_processed_only_if_ingested=mark_processed_only_if_ingested,
    )

    seen_message_ids: set[str] = set(known_message_ids or ())

    for email in emails:
        result.message_ids.append(email.message_id)
        if email.mailbox_email:
            result.message_mailbox_emails[email.message_id] = email.mailbox_email
        if email.graph_id:
            result.message_graph_ids[email.message_id] = email.graph_id

        if email.message_id in seen_message_ids:
            logger.info(
                "email_ingest_skipped",
                reason="message_already_imported",
                message_id=email.message_id,
                mailbox=email.mailbox_email,
                subject=email.subject,
            )
            await log_event(
                session,
                "email_skipped",
                detail={
                    "reason": "message_already_imported",
                    "message_id": email.message_id,
                },
            )
            result.preskip_exceptions[email.message_id] = "message_already_imported"
            continue

        try:
            async with session.begin_nested():
                await _ingest_single_email(
                    session,
                    email,
                    result=result,
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    tenant_name=tenant_name,
                    connected_mailbox_id=connected_mailbox_id,
                    enabled_capture_rules=enabled_capture_rules,
                    capture_config=capture_config,
                    mark_processed=mark_processed,
                    mark_processed_only_if_ingested=mark_processed_only_if_ingested,
                )
        except IntegrityError as exc:
            logger.warning(
                "email_ingest_integrity_error",
                message_id=email.message_id,
                mailbox=email.mailbox_email,
                subject=email.subject,
                error=str(exc),
            )
            from app.services.ingest.ingest_skip_service import log_ingest_skip

            await log_ingest_skip(
                session,
                reason="ingest_integrity_error",
                channel="email",
                tenant_id=tenant_id,
                message_id=email.message_id,
                mailbox=email.mailbox_email,
                exc_type=type(exc).__name__,
                extra={"subject": email.subject},
            )
            result.preskip_exceptions[email.message_id] = "integrity_error"
            continue
        except Exception as exc:
            # One bad attachment/subject must not abort the rest of the mailbox poll.
            from app.services.credit_service import PlanFeatureBlockedError

            if isinstance(exc, PlanFeatureBlockedError):
                raise
            logger.warning(
                "email_ingest_message_failed",
                message_id=email.message_id,
                mailbox=email.mailbox_email,
                subject=email.subject,
                error=str(exc),
            )
            from app.services.ingest.ingest_skip_service import log_ingest_skip

            await log_ingest_skip(
                session,
                reason="ingest_message_failed",
                channel="email",
                tenant_id=tenant_id,
                message_id=email.message_id,
                mailbox=email.mailbox_email,
                exc_type=type(exc).__name__,
                extra={"subject": email.subject, "error": str(exc)[:500]},
            )
            result.preskip_exceptions[email.message_id] = "ingest_error"
            continue

        seen_message_ids.add(email.message_id)

    logger.info(
        "email_ingest_batch_done",
        tenant_id=str(tenant_id),
        connected_mailbox_id=connected_mailbox_id,
        ingested_count=result.ingested_count,
        message_count=len(result.message_ids),
        skip_count=len(result.preskip_exceptions),
        skip_reasons=dict(result.preskip_exceptions),
    )

    return result


async def _ingest_single_email(
    session: AsyncSession,
    email: RawEmail,
    *,
    result: EmailIngestResult,
    tenant_id: int,
    tenant_slug: str,
    tenant_name: str | None,
    connected_mailbox_id: int | None,
    enabled_capture_rules: list,
    capture_config: RuleBookConfigPayload,
    mark_processed: bool,
    mark_processed_only_if_ingested: bool,
) -> None:
    _ = enabled_capture_rules
    ingested_before = result.ingested_count
    duplicate_handled = False

    from app.services.ingest.ingest_skip_service import log_ingest_skip

    for drop in list(email.attachment_drops):
        await log_ingest_skip(
            session,
            reason=drop.get("reason") or "attachment_record_invalid",
            channel="email",
            tenant_id=tenant_id,
            message_id=email.message_id,
            mailbox=email.mailbox_email,
            filename=drop.get("filename") or None,
        )
    email.attachment_drops.clear()

    if not email.attachments:
        logger.info(
            "email_ingest_skipped",
            reason="no_attachments",
            message_id=email.message_id,
            mailbox=email.mailbox_email,
            subject=email.subject,
        )
        await log_event(
            session,
            "email_skipped",
            detail={"reason": "no_attachments", "message_id": email.message_id},
        )
        result.preskip_exceptions[email.message_id] = "no_attachments"
        _maybe_finish_email_message(
            email,
            mark_processed=mark_processed,
            mark_processed_only_if_ingested=mark_processed_only_if_ingested,
            ingested_before=ingested_before,
            ingested_after=result.ingested_count,
        )
        return

    attachments = filter_invoice_attachments(email)
    if not attachments:
        raw_names = [att.filename for att in email.attachments]
        logger.info(
            "email_ingest_skipped",
            reason="no_invoice_attachments",
            message_id=email.message_id,
            mailbox=email.mailbox_email,
            subject=email.subject,
            attachment_names=raw_names,
        )
        await log_event(
            session,
            "email_skipped",
            detail={"reason": "no_invoice_attachments", "message_id": email.message_id},
        )
        result.preskip_exceptions[email.message_id] = "no_invoice_attachments"
        _maybe_finish_email_message(
            email,
            mark_processed=mark_processed,
            mark_processed_only_if_ingested=mark_processed_only_if_ingested,
            ingested_before=ingested_before,
            ingested_after=result.ingested_count,
        )
        return

    # Gate: ingest capture rule first, then employee master for catch-all / Team Expenses.
    # Specific Purchase/Sales ``from`` rules do not require an employee match.
    from app.services.ingest.ingest_capture_service import employee_bypass_capture_rule
    from app.services.master_data.master_data_service import list_employee_masters
    from app.services.purchase.team_expense_validator import find_employee_by_sender

    employees = await list_employee_masters(session, tenant_id)
    matched_employee = find_employee_by_sender(employees, email.sender)

    capture_rule_blocked = False
    for att in attachments:
        capture_rule = evaluate_ingest_capture(email, att, capture_config)
        if not capture_rule:
            # No human-authored rule: employees may still ingest via registry bypass.
            if matched_employee is not None:
                capture_rule = employee_bypass_capture_rule(email.mailbox_email or "")
                await log_event(
                    session,
                    "email_employee_bypass",
                    detail={
                        "reason": "employee_registry_match",
                        "message_id": email.message_id,
                        "sender": email.sender,
                        "employee_name": matched_employee.name,
                        "subject": email.subject,
                        "attachment": att.filename,
                        "mailbox": email.mailbox_email,
                    },
                )
            else:
                capture_rule_blocked = True
                log_ingest_capture_decision(email, att, capture_config, matched_rule=None)
                await log_event(
                    session,
                    "email_skipped",
                    detail={
                        "reason": "no_capture_rule_match",
                        "message_id": email.message_id,
                        "sender": email.sender,
                        "subject": email.subject,
                        "attachment": att.filename,
                        "mailbox": email.mailbox_email,
                    },
                )
                continue

        # Catch-all / Team Expenses: rule matched, but sender must be an employee.
        if capture_rule_requires_employee_sender(capture_rule) and matched_employee is None:
            capture_rule_blocked = True
            log_ingest_capture_decision(email, att, capture_config, matched_rule=capture_rule)
            await log_event(
                session,
                "email_skipped",
                detail={
                    "reason": "sender_not_employee",
                    "message_id": email.message_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "attachment": att.filename,
                    "mailbox": email.mailbox_email,
                    "capture_rule_id": capture_rule.id,
                    "capture_rule_name": capture_rule.name,
                },
            )
            result.preskip_exceptions[email.message_id] = "sender_not_employee"
            continue

        log_ingest_capture_decision(email, att, capture_config, matched_rule=capture_rule)

        file_hash = compute_sha256_bytes(att.data)
        content_fingerprint: str | None = None
        business_fingerprint: str | None = None
        identity_fields: dict[str, str] | None = None
        prefetched_extraction = None
        if att.filename and att.filename.lower().endswith(".pdf"):
            import tempfile
            from pathlib import Path

            from app.services.extraction.document_identity_service import (
                compute_business_fingerprint_from_pages,
                extract_identity_fields_from_pages,
                identity_field_keys_from_catalogue,
            )
            from app.services.extraction.pdf_content_fingerprint import (
                compute_pdf_content_fingerprint_from_pages,
            )
            from app.services.extraction.pdf_page_text_service import extract_pdf_page_texts

            custom_keys = identity_field_keys_from_catalogue(capture_config.document_types)
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                    handle.write(att.data)
                    tmp_path = Path(handle.name)
                prefetched_extraction = extract_pdf_page_texts(tmp_path)
                pages_for_fp = prefetched_extraction.pages
                content_fingerprint = compute_pdf_content_fingerprint_from_pages(pages_for_fp)
                identity_fields = extract_identity_fields_from_pages(
                    pages_for_fp,
                    custom_field_keys=custom_keys,
                )
                business_fingerprint = compute_business_fingerprint_from_pages(
                    pages_for_fp,
                    custom_field_keys=custom_keys,
                )
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

        # Exceptions re-poll: avoid creating another shadow every cycle (adapter-only quirk).
        existing = await find_existing_ingest_duplicate(
            session,
            tenant_id=tenant_id,
            file_hash=file_hash,
            content_fingerprint=content_fingerprint,
            business_fingerprint=business_fingerprint,
            identity_fields=identity_fields,
        )
        if existing is not None and email.poll_folder == "exceptions":
            dup_decision = evaluate_file_hash_duplicate(existing)
            if dup_decision.action == "shadow_duplicate":
                existing.email_message_id = email.message_id
                await log_duplicate_skipped(
                    session,
                    existing.id,
                    detail={
                        "filename": att.filename,
                        "message_id": email.message_id,
                        "mailbox": email.mailbox_email,
                        "source": "email",
                        "poll_folder": email.poll_folder,
                        "note": "exceptions_repoll_skipped",
                        **original_document_audit_fields(existing),
                    },
                )
                duplicate_handled = True
                continue

        from app.services.ingest.canonical_intake_service import canonical_intake_enabled_for

        if not canonical_intake_enabled_for("email") and existing is not None:
            outcome = await resolve_ingest_duplicate(
                session,
                tenant_id=tenant_id,
                existing=existing,
                file_hash=file_hash,
                content_fingerprint=content_fingerprint,
                business_fingerprint=business_fingerprint,
                capture_source="email",
                connected_mailbox_id=connected_mailbox_id,
                email_sender=email.sender or None,
                email_subject=email.subject or None,
                email_attachment_name=att.filename,
                email_message_id=email.message_id,
                extra_detail={
                    "filename": att.filename,
                    "message_id": email.message_id,
                    "mailbox": email.mailbox_email,
                    "source": "email",
                    "poll_folder": email.poll_folder,
                },
            )
            if outcome.handled:
                duplicate_handled = True
                if outcome.action == "reingest_rejected" and outcome.invoice_id is not None:
                    inv = await session.get(Invoice, outcome.invoice_id)
                    if inv is not None:
                        from app.services.sales.so_reference import ensure_invoice_so_reference

                        ensure_invoice_so_reference(inv)
                        await apply_ingest_capture(session, inv, email, att)
                        result.ingested_count += 1
                continue

        vendor_slug = await resolve_capture_slug(
            session, email.sender, tenant_id=tenant_id
        )
        fanout = await ingest_file_with_fanout(
            session,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            filename=att.filename,
            data=att.data,
            source=IngestSourceMetadata(
                storage_vendor_slug=vendor_slug,
                email_sender=email.sender or None,
                email_subject=email.subject or None,
                email_message_id=email.message_id,
                email_attachment_name=att.filename,
                connected_mailbox_id=connected_mailbox_id,
                capture_source="email",
            ),
            prefetched_extraction=prefetched_extraction,
        )
        if fanout.duplicate_handled:
            duplicate_handled = True

        for segment_index, invoice_id in enumerate(fanout.invoice_ids):
            inv = await session.get(Invoice, invoice_id)
            assert inv is not None
            if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
                continue
            await apply_ingest_capture(session, inv, email, att)
            await log_event(
                session,
                "email_ingested",
                invoice_id=inv.id,
                detail={
                    "subject": email.subject,
                    "sender": email.sender,
                    "message_id": email.message_id,
                    "vendor_slug": vendor_slug,
                    "storage": inv.raw_file_path,
                    "parent_file_hash": fanout.parent_file_hash,
                    "segment_index": segment_index,
                    "segment_count": fanout.segment_count,
                    "action": fanout.action,
                },
            )
            result.ingested_count += 1

    if capture_rule_blocked and result.ingested_count == ingested_before and not duplicate_handled:
        result.preskip_exceptions.setdefault(email.message_id, "no_capture_rule_match")

    _maybe_finish_email_message(
        email,
        mark_processed=mark_processed,
        mark_processed_only_if_ingested=mark_processed_only_if_ingested,
        ingested_before=ingested_before,
        ingested_after=result.ingested_count,
        force=duplicate_handled and result.ingested_count == ingested_before,
    )


async def _maybe_reprocess_held_commercial_siblings(
    session: AsyncSession,
    invoice: Invoice,
    *,
    route_target: str,
    anchor_ref: str | None,
) -> None:
    anchor = (anchor_ref or "").strip()
    if not anchor:
        return
    from app.services.dossier.dossier_reprocess_service import (
        reprocess_held_commercial_invoices_on_anchor,
    )

    await reprocess_held_commercial_invoices_on_anchor(
        session,
        tenant_id=invoice.tenant_id,
        route_target=route_target,
        anchor_ref=anchor,
        triggering_invoice_id=invoice.id,
    )


async def _finish_purchase_supporting_document(session: AsyncSession, invoice: Invoice) -> None:
    """PO / GRN documents: sync register, skip AP journal and GL mapping."""
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO, sync_purchase_document
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.invoice.non_posting_document_service import finish_non_posting_document
    from app.services.classification.document_type_playbook_profile_service import clear_invoice_gl_mapping

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    linked_po = await load_purchase_order_for_invoice(session, loaded)
    await _sync_and_evaluate_invoice(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    clear_invoice_gl_mapping(invoice)
    clear_invoice_gl_mapping(loaded)

    await sync_purchase_document(session, invoice)
    if invoice.evaluation_status == EVAL_AWAITING_PO:
        invoice.status = InvoiceStatus.EXCEPTION
        await session.flush()
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    if linked_po:
        await reconcile_dossier_vendor(
            session,
            invoice,
            linked_po,
            document_type=invoice.purchase_document_type,
        )

    await _maybe_reprocess_held_commercial_siblings(
        session,
        invoice,
        route_target=ROUTE_PURCHASE,
        anchor_ref=invoice.po_reference,
    )

    await finish_non_posting_document(
        session,
        invoice,
        audit_event="purchase_document_processed",
        detail={"purchase_document_type": invoice.purchase_document_type},
    )
    await _safe_auto_learn(session, invoice)


async def _finish_sales_supporting_document(session: AsyncSession, invoice: Invoice) -> None:
    """SO / DN documents: sync register, skip AR journal and GL mapping."""
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO, sync_sales_document
    from app.services.sales.sales_match_service import load_sales_order_for_invoice
    from app.services.invoice.non_posting_document_service import finish_non_posting_document
    from app.services.classification.document_type_playbook_profile_service import clear_invoice_gl_mapping

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await load_sales_order_for_invoice(session, loaded)
    await _sync_and_evaluate_invoice(session, loaded)
    await sync_invoice_blob_path(session, loaded, parsed_vendor=loaded.vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    clear_invoice_gl_mapping(invoice)
    clear_invoice_gl_mapping(loaded)

    await sync_sales_document(session, invoice)
    if invoice.evaluation_status == EVAL_AWAITING_SO:
        invoice.status = InvoiceStatus.EXCEPTION
        await session.flush()
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    await _maybe_reprocess_held_commercial_siblings(
        session,
        invoice,
        route_target=ROUTE_SALES,
        anchor_ref=invoice.so_reference,
    )

    await finish_non_posting_document(
        session,
        invoice,
        audit_event="sales_document_processed",
        detail={"sales_document_type": invoice.sales_document_type},
    )
    await _safe_auto_learn(session, invoice)


async def _apply_parsed_to_invoice(
    session: AsyncSession,
    *,
    invoice: Invoice,
    loaded: Invoice,
    parsed: InvoiceData,
    config,
    preserve_existing: bool = False,
    org=None,
    trace: object | None = None,
) -> str | None:
    """Write extracted AP fields onto invoice rows (post-classification extract phase)."""
    if preserve_existing:
        from app.utils.abn_validator import storage_abn

        resolved_vendor = (loaded.vendor or "").strip() or None
        if not resolved_vendor:
            resolved_vendor = resolve_canonical_vendor_name(
                invoice.tenant_id,
                vendor_names=[parsed.vendor],
                abns=[parsed.abn],
                config=config,
            )
            if not resolved_vendor and parsed.vendor and is_plausible_vendor_name(parsed.vendor):
                resolved_vendor = parsed.vendor
            if resolved_vendor:
                invoice.vendor = resolved_vendor
                loaded.vendor = resolved_vendor

        _apply_parsed_scalar(invoice, "abn", storage_abn(parsed.abn) if parsed.abn else None)
        _apply_parsed_scalar(invoice, "billing_address", parsed.billing_address)
        _apply_parsed_scalar(invoice, "bank_bsb", parsed.bank_bsb)
        _apply_parsed_scalar(invoice, "bank_account", parsed.bank_account)
        _apply_parsed_scalar(invoice, "invoice_no", parsed.invoice_no)
        _apply_parsed_scalar(invoice, "po_reference", parsed.po_reference)
        _apply_parsed_scalar(invoice, "cost_centre", parsed.cost_centre)
        _apply_parsed_scalar(invoice, "invoice_date", parsed.invoice_date)
        _apply_parsed_scalar(invoice, "due_date", parsed.due_date)
        _apply_parsed_scalar(invoice, "subtotal", plausible_money(parsed.subtotal))
        _apply_parsed_scalar(invoice, "gst", plausible_money(parsed.gst))
        _apply_parsed_scalar(invoice, "total", plausible_money(parsed.total))
        from app.services.extraction.gst_rate import resolve_gst_rate_percent

        _apply_parsed_scalar(
            invoice,
            "gst_rate",
            resolve_gst_rate_percent(parsed, allow_inference=True),
        )
        if _scalar_field_empty(invoice.currency):
            invoice.currency = parsed.currency
        if _scalar_field_empty(invoice.document_text):
            from app.services.extraction.document_text import cap_document_text

            invoice.document_text = cap_document_text(parsed.document_text)
        if not await _invoice_has_persisted_line_items(session, loaded):
            await _replace_line_items(session, loaded, parsed.line_items, trace=trace)
        elif "line_items" in sa_inspect(loaded).unloaded:
            await session.refresh(loaded, attribute_names=["line_items"])

        from app.services.extraction.extraction_field_values import apply_parsed_extraction_fields

        apply_parsed_extraction_fields(invoice, parsed, preserve_existing=True)

        loaded.abn = invoice.abn
        loaded.billing_address = invoice.billing_address
        loaded.bank_bsb = invoice.bank_bsb
        loaded.bank_account = invoice.bank_account
        loaded.invoice_no = invoice.invoice_no
        loaded.po_reference = invoice.po_reference
        loaded.so_reference = invoice.so_reference
        loaded.cost_centre = invoice.cost_centre
        loaded.invoice_date = invoice.invoice_date
        loaded.due_date = invoice.due_date
        loaded.subtotal = invoice.subtotal
        loaded.gst = invoice.gst
        loaded.gst_rate = invoice.gst_rate
        loaded.total = invoice.total
        loaded.currency = invoice.currency
        loaded.document_text = invoice.document_text
        loaded.document_heading = invoice.document_heading
        loaded.extracted_fields = invoice.extracted_fields
        from app.services.sales.counterparty_service import sync_invoice_counterparty

        sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
        loaded.vendor = invoice.vendor
        return invoice.vendor

    from app.utils.abn_validator import storage_abn

    invoice.vendor = parsed.vendor
    invoice.abn = storage_abn(parsed.abn)
    parsed.abn = invoice.abn
    invoice.billing_address = parsed.billing_address
    invoice.bank_bsb = parsed.bank_bsb
    invoice.bank_account = parsed.bank_account
    from app.services.extraction.invoice_no_sanitizer import (
        apply_invoice_no_secondary,
        extract_invoice_no_from_text,
        sanitize_invoice_no_parts,
    )

    primary, secondary = sanitize_invoice_no_parts(parsed.invoice_no)
    if not primary:
        primary = extract_invoice_no_from_text(parsed.document_text or "")
        secondary = None
    invoice.invoice_no = primary
    parsed.invoice_no = primary
    parsed.extracted_fields = apply_invoice_no_secondary(parsed.extracted_fields, secondary)
    invoice.po_reference = parsed.po_reference
    invoice.cost_centre = parsed.cost_centre
    invoice.invoice_date = parsed.invoice_date
    invoice.due_date = parsed.due_date
    invoice.subtotal = plausible_money(parsed.subtotal)
    invoice.gst = plausible_money(parsed.gst)
    invoice.total = plausible_money(parsed.total)
    from app.services.extraction.gst_rate import resolve_gst_rate_percent

    invoice.gst_rate = resolve_gst_rate_percent(parsed, allow_inference=True)
    invoice.currency = parsed.currency
    from app.services.extraction.document_text import cap_document_text
    from app.services.purchase.po_reference import ensure_invoice_po_reference, extract_po_reference_from_text

    invoice.document_text = cap_document_text(parsed.document_text)
    from app.services.extraction.extraction_field_values import apply_parsed_extraction_fields

    apply_parsed_extraction_fields(invoice, parsed)
    if not invoice.po_reference:
        extracted = extract_po_reference_from_text(invoice.document_text)
        if extracted:
            invoice.po_reference = extracted
            parsed.po_reference = extracted

    from app.services.sales.so_reference import ensure_invoice_so_reference, sanitize_cross_book_linkage_references

    ensure_invoice_so_reference(invoice)
    ensure_invoice_po_reference(invoice)
    sanitize_cross_book_linkage_references(invoice)

    from app.services.sales.counterparty_service import sync_invoice_counterparty

    sync_invoice_counterparty(invoice, config=config, parsed=parsed, org=org)
    _finalize_vendor_counterparty(invoice, parsed=parsed, config=config)

    loaded.vendor = invoice.vendor
    loaded.abn = invoice.abn
    loaded.billing_address = invoice.billing_address
    loaded.bank_bsb = invoice.bank_bsb
    loaded.bank_account = invoice.bank_account
    loaded.invoice_no = invoice.invoice_no
    loaded.po_reference = invoice.po_reference
    loaded.so_reference = invoice.so_reference
    loaded.cost_centre = invoice.cost_centre
    loaded.invoice_date = invoice.invoice_date
    loaded.due_date = invoice.due_date
    loaded.subtotal = invoice.subtotal
    loaded.gst = invoice.gst
    loaded.gst_rate = invoice.gst_rate
    loaded.total = invoice.total
    loaded.currency = invoice.currency
    loaded.document_text = invoice.document_text
    loaded.document_heading = invoice.document_heading
    loaded.extracted_fields = invoice.extracted_fields

    await _replace_line_items(session, loaded, parsed.line_items, trace=trace)
    return invoice.vendor


async def prepare_route_register_before_posting(
    session: AsyncSession,
    invoice: Invoice,
    *,
    bypass_review_gates: bool,
) -> bool:
    """Infer PO/SO roles, sync registers, and finish supporting documents.

    Returns True when the caller must stop (supporting doc processed or anchor hold).
    """
    from app.services.purchase.purchase_document_service import (
        EVAL_AWAITING_PO,
        apply_purchase_document_type_after_eval,
        sync_purchase_document,
    )
    from app.services.sales.sales_document_service import (
        EVAL_AWAITING_SO,
        apply_sales_document_type_after_eval,
        sync_sales_document,
    )

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    await apply_purchase_document_type_after_eval(session, loaded)
    await apply_sales_document_type_after_eval(session, loaded)
    invoice.purchase_document_type = loaded.purchase_document_type
    invoice.sales_document_type = loaded.sales_document_type
    invoice.po_reference = loaded.po_reference
    invoice.so_reference = loaded.so_reference

    route = (loaded.route_target or "").strip()
    purchase_doc_type = (loaded.purchase_document_type or "").strip().lower()
    if route == ROUTE_PURCHASE:
        await sync_purchase_document(session, loaded)
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.po_reference = loaded.po_reference
        invoice.evaluation_status = loaded.evaluation_status
        if purchase_doc_type in ("po", "grn") and not bypass_review_gates:
            await _finish_purchase_supporting_document(session, invoice)
            return True
        if (
            loaded.status == InvoiceStatus.EXCEPTION
            and loaded.evaluation_status == EVAL_AWAITING_PO
        ):
            hold_bypass = bypass_review_gates or override_bypasses_purchase_hold(invoice)
            if hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if override_bypasses_purchase_hold(invoice) and not bypass_review_gates:
                    await _log_processing_override_skip(session, invoice, "playbook")
                loaded.evaluation_status = EVAL_AUTO_CODED
                invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.VALIDATING
                invoice.status = InvoiceStatus.VALIDATING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return True

    sales_doc_type = (loaded.sales_document_type or "").strip().lower()
    if route == ROUTE_SALES:
        await sync_sales_document(session, loaded)
        invoice.sales_document_type = loaded.sales_document_type
        invoice.so_reference = loaded.so_reference
        invoice.evaluation_status = loaded.evaluation_status
        if sales_doc_type in ("so", "dn") and not bypass_review_gates:
            await _finish_sales_supporting_document(session, invoice)
            return True
        if (
            loaded.status == InvoiceStatus.EXCEPTION
            and loaded.evaluation_status == EVAL_AWAITING_SO
        ):
            hold_bypass = bypass_review_gates or override_bypasses_sales_hold(invoice)
            if hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if override_bypasses_sales_hold(invoice) and not bypass_review_gates:
                    await _log_processing_override_skip(session, invoice, "playbook")
                loaded.evaluation_status = EVAL_AUTO_CODED
                invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.VALIDATING
                invoice.status = InvoiceStatus.VALIDATING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return True

    return False


async def resume_invoice_posting_pipeline(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
) -> None:
    """Resume mapping→journal→post using persisted extract fields (no OCR/LLM/extract)."""
    cfg: RuleBookConfigPayload = config or await load_config_for_tenant(session, invoice.tenant_id)
    tenant_row = await session.get(Tenant, invoice.tenant_id)
    org = org_context_from_config(cfg, tenant_row)
    bypass_review_gates = await human_approved_payable_bypass(session, invoice)

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    parsed = invoice_data_from_invoice(loaded)
    resolved_vendor = loaded.vendor

    route = (loaded.route_target or "").strip()
    if route == ROUTE_PURCHASE:
        from app.services.purchase.purchase_document_service import (
            EVAL_AWAITING_PO,
            sync_purchase_document,
        )

        await sync_purchase_document(session, loaded)
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.po_reference = loaded.po_reference
        invoice.evaluation_status = loaded.evaluation_status
        if (
            loaded.status == InvoiceStatus.EXCEPTION
            and loaded.evaluation_status == EVAL_AWAITING_PO
        ):
            purchase_hold_bypass = bypass_review_gates or override_bypasses_purchase_hold(invoice)
            if purchase_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if override_bypasses_purchase_hold(invoice) and not bypass_review_gates:
                    await _log_processing_override_skip(session, invoice, "playbook")
                loaded.evaluation_status = EVAL_AUTO_CODED
                invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.MAPPING
                invoice.status = InvoiceStatus.MAPPING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return
    elif route == ROUTE_SALES:
        from app.services.sales.sales_document_service import EVAL_AWAITING_SO, sync_sales_document

        await sync_sales_document(session, loaded)
        invoice.sales_document_type = loaded.sales_document_type
        invoice.so_reference = loaded.so_reference
        invoice.evaluation_status = loaded.evaluation_status
        if (
            loaded.status == InvoiceStatus.EXCEPTION
            and loaded.evaluation_status == EVAL_AWAITING_SO
        ):
            sales_hold_bypass = bypass_review_gates or override_bypasses_sales_hold(invoice)
            if sales_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if override_bypasses_sales_hold(invoice) and not bypass_review_gates:
                    await _log_processing_override_skip(session, invoice, "playbook")
                loaded.evaluation_status = EVAL_AUTO_CODED
                invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.MAPPING
                invoice.status = InvoiceStatus.MAPPING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return

    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.MAPPING
    await session.flush()

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.sales.sales_match_service import load_sales_order_for_invoice

    linked_po = await load_purchase_order_for_invoice(session, loaded)
    linked_so = await load_sales_order_for_invoice(session, loaded)
    map_config = cfg
    mapping, mapping_detail = _resolve_header_mapping(
        loaded,
        config=map_config,
        purchase_order=linked_po,
        sales_order=linked_so,
    )
    from app.services.purchase.team_expense_kind_service import (
        resolve_team_expense_header_mapping,
    )

    mapping, mapping_detail = await resolve_team_expense_header_mapping(
        session,
        loaded,
        map_config,
        mapping=mapping,
        detail=mapping_detail,
    )
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=cfg,
        org=org,
    )
    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = loaded.evaluation_status
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    await log_event(
        session,
        "mapping_applied",
        invoice_id=invoice.id,
        detail={
            "account_code": mapping.account_code,
            "account_name": mapping.account_name,
            "rule_type": mapping_detail.rule_type,
            "match_reason": mapping_detail.match_reason,
            "resume": "variance_approval",
        },
    )

    if not should_skip(invoice, "line_gl_mapping"):
        from app.services.classification.line_gl_mapping_service import apply_line_gl_mapping

        await apply_line_gl_mapping(session, loaded, map_config)

    if await _hold_for_missing_line_sub_ledgers(
        session,
        invoice,
        loaded,
        map_config,
        bypass_review_gates=bypass_review_gates,
    ):
        return

    if (
        requires_gl_mapping_review(
            loaded,
            mapping_detail,
            document_types=list(cfg.document_types),
        )
        and not bypass_review_gates
        and not should_skip(invoice, "mapping_review")
    ):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    await _mark_deterministic_mapping_auto_coded(
        session,
        invoice,
        loaded,
        mapping_detail,
    )

    if await apply_team_expense_approval_gate(session, invoice):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    from app.services.match.match_variance_gate_service import (
        build_variance_gate_audit_detail,
        evaluate_match_variance_gate,
    )

    variance_gate = await evaluate_match_variance_gate(session, loaded, config=cfg)
    if variance_gate.blocked:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "three_way_match_variance_unapproved",
            invoice_id=invoice.id,
            detail=build_variance_gate_audit_detail(variance_gate),
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.JOURNALING
    await session.flush()
    if await halt_if_missing_accrual_date(session, invoice):
        return
    existing_entries = (
        await session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(invoice.tenant_id, invoice.id),
                JournalEntry.entry_kind == JournalEntryKind.INVOICE_ACCRUAL,
            )
        )
    ).scalars().all()
    for entry in existing_entries:
        await session.delete(entry)
    await session.flush()
    backfill_invoice_amounts_from_sources(loaded)
    invoice.subtotal = loaded.subtotal
    invoice.gst = loaded.gst
    invoice.total = loaded.total
    vendor_reg_id, customer_reg_id = await resolve_counterparty_registry_ids_for_journal(
        session, invoice
    )
    from app.services.master_data.party_coa_subledger_service import (
        resolve_invoice_control_mapping,
    )

    control_mapping = await resolve_invoice_control_mapping(
        session,
        invoice,
        cfg,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
    )
    from app.tenant_settings import tenant_currency
    from app.services.purchase.team_expense_advance_service import (
        resolve_claim_advance_available,
    )

    tenant = await session.get(Tenant, invoice.tenant_id)
    base_currency = tenant_currency(tenant)
    advance_available = await resolve_claim_advance_available(session, invoice, cfg)
    journal_lines = generate_entries(
        invoice,
        mapping,
        config=cfg,
        sales_order=linked_so,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
        control_mapping=control_mapping,
        base_currency=base_currency,
        advance_available=advance_available,
    )
    if not is_balanced(journal_lines):
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "journal_unbalanced",
            invoice_id=invoice.id,
            detail={
                "subtotal": float(invoice.subtotal or 0),
                "gst": float(invoice.gst or 0),
                "total": float(invoice.total or 0),
                "resume": "variance_approval",
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    unresolved_control = get_unresolved_control_accounts(invoice=invoice, config=map_config)
    if unresolved_control:
        invoice.status = InvoiceStatus.EXCEPTION
        fallback = resolve_fallback_account_mapping(map_config)
        await log_event(
            session,
            "journal_control_account_unresolved",
            invoice_id=invoice.id,
            detail={
                "unresolved": unresolved_control,
                "fallback_code": fallback.account_code,
                "fallback_name": fallback.account_name,
                "route_target": invoice.route_target,
                "resume": "variance_approval",
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    try:
        await persist_journal_lines(
            session, invoice, journal_lines, base_currency=base_currency
        )
    except PeriodClosedError as exc:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "journal_period_closed",
            invoice_id=invoice.id,
            detail={"reason": str(exc), "route_target": invoice.route_target},
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.RECONCILING
    await session.flush()
    recon_date = effective_invoice_recon_date(invoice)
    if recon_date is None:
        await halt_if_missing_accrual_date(session, invoice)
        return
    recon = await reconcile_daily(
        session,
        recon_date,
        tenant_id=invoice.tenant_id,
        current_invoice=invoice,
        config=cfg,
    )
    await save_reconciliation(session, recon, tenant_id=invoice.tenant_id)
    if recon.halted:
        route_target = (invoice.route_target or "").strip()
        non_blocking_recon = route_target in (ROUTE_TEAM, ROUTE_EXPENSES) or bypass_review_gates
        if not non_blocking_recon:
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "reconciliation_halted",
                invoice_id=invoice.id,
                detail={"reason": recon.halt_reason, "resume": "variance_approval"},
            )
            await _purge_accruals_after_incomplete_halt(
                session, invoice, reason="reconciliation_halted"
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    pre_post = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await _vendor_hold_unless_skipped(session, pre_post):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = pre_post.evaluation_status
        await _purge_accruals_after_incomplete_halt(
            session, invoice, reason="vendor_registration_hold"
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    # Capture before _mark_invoice_processed clears processing_overrides.
    playbook_bypasses_po_hold = override_bypasses_purchase_hold(invoice)
    playbook_bypasses_so_hold = override_bypasses_sales_hold(invoice)
    _mark_invoice_processed(invoice)
    await session.flush()
    await record_team_expense_processed(session, invoice)
    from app.services.purchase.purchase_document_service import (
        is_commercial_purchase_invoice,
        sync_purchase_document,
    )

    await sync_purchase_document(session, invoice)
    if await _halt_or_bypass_purchase_awaiting_po(
        session,
        invoice,
        bypass_review_gates=bypass_review_gates,
        playbook_bypasses_po_hold=playbook_bypasses_po_hold,
    ):
        return
    if is_commercial_purchase_invoice(invoice):
        from app.services.payments.settlement_service import ensure_payment_with_audit

        await ensure_payment_with_audit(session, invoice)

    from app.services.sales.sales_document_service import (
        is_commercial_sales_invoice,
        sync_sales_document,
    )

    await sync_sales_document(session, invoice)
    if (invoice.route_target or "").strip() == ROUTE_SALES and await _halt_or_bypass_sales_awaiting_so(
        session,
        invoice,
        bypass_review_gates=bypass_review_gates,
        playbook_bypasses_so_hold=playbook_bypasses_so_hold,
    ):
        return
    if is_commercial_sales_invoice(invoice):
        from app.services.payments.settlement_service import ensure_receivable_with_audit

        await ensure_receivable_with_audit(session, invoice)
    await _safe_auto_learn(session, invoice)
    if await _stop_if_not_processed_for_publish(session, invoice):
        return
    await log_event(
        session,
        "invoice_processed",
        invoice_id=invoice.id,
        detail={
            "route_target": invoice.route_target,
            "status": invoice.status.value,
            "vendor": invoice.vendor,
            "amount": float(invoice.total) if invoice.total is not None else None,
            "resume": "variance_approval",
        },
    )
    from app.services.integration.publish_service import publish_invoice_to_ledger

    await publish_invoice_to_ledger(
        session,
        invoice,
        auto=True,
        skip_if_insufficient_credits=True,
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)


async def process_invoice(session: AsyncSession, invoice: Invoice) -> None:
    """Parse → validate → map → journal → reconcile for one invoice."""
    if invoice.status in (
        InvoiceStatus.PROCESSED,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    ):
        return

    from app.services.prompt_registry import warm_prompt_cache

    try:
        await warm_prompt_cache(session)
    except Exception:
        # Registry warm must never poison the invoice transaction (e.g. concurrent
        # prompt version insert). Rollback clears PendingRollbackError; pipeline
        # continues on code catalog defaults via resolve_system_prompt.
        try:
            await session.rollback()
        except Exception:
            pass

    await assign_document_ref(session, invoice)

    bypass_review_gates = await human_approved_payable_bypass(session, invoice)
    from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits
    from app.services.invoice.processing_override_catalog import (
        consume_preserve_extracted_fields,
    )

    await session.refresh(invoice, attribute_names=["processing_overrides"])

    preserve_from_requeue = consume_preserve_extracted_fields(invoice)
    preserve_extracted_fields = (
        preserve_from_requeue
        or bypass_review_gates
        or await invoice_has_manual_field_edits(
            session,
            invoice.id,
            tenant_id=invoice.tenant_id,
        )
    )

    if not invoice.raw_file_path:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(invoice, reason="no_stored_path"),
        )
        return

    invoice.status = InvoiceStatus.PARSING
    await session.flush()

    tenant_row = await session.get(Tenant, invoice.tenant_id)
    config = await load_config_for_tenant(session, invoice.tenant_id)
    org = org_context_from_config(config, tenant_row)
    ai_cfg = ai_classification_from_config(config)
    doc_provider = DocumentAiProvider.from_config(ai_cfg.document_ai_provider)
    provider_token = doc_provider.value

    human_locked_dt = await human_confirmed_document_type(session, invoice_id=invoice.id)
    if human_locked_dt:
        locked_defn = get_document_type_definition(
            human_locked_dt,
            document_types=config.document_types,
        )
        if locked_defn is None or not locked_defn.enabled:
            human_locked_dt = None

    try:
        await phase_storage_verify(
            session,
            invoice,
            document_ai_provider=provider_token,
        )
        await phase_file_validity(
            session,
            invoice,
            document_ai_provider=provider_token,
        )
    except OcrFailed as exc:
        reason = str(exc) or "stored_file_missing"
        invoice.status = InvoiceStatus.EXCEPTION
        if reason in {"file_encrypted", "unsupported_file_type", "file_corrupted", "file_too_large", "file_empty"}:
            invoice.evaluation_status = EVAL_NEEDS_RESCAN
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason=reason,
                path=invoice.raw_file_path,
                document_ai_provider=provider_token,
            ),
        )
        if reason in {"file_encrypted", "unsupported_file_type", "file_corrupted", "file_too_large", "file_empty"}:
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "file_validity",
                    "review_reasons": [reason],
                    "document_ai_provider": provider_token,
                },
            )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    skip_classify_gate = bool(human_locked_dt)
    locked_dt_code = (invoice.document_type_code or "").strip().upper()
    classification_override = should_skip(invoice, "classification") and bool(locked_dt_code)
    if classification_override and not human_locked_dt:
        skip_classify_gate = True
    classify_llm: LlmDocumentResult | None = None
    gate_result = None
    vendor_drift_result = None
    confirmed_dt = human_locked_dt or (locked_dt_code if classification_override else "")

    vision_page_images: list[bytes] = []
    readiness = None

    understand = await phase_vision_understand(
        session,
        invoice,
        doc_provider=doc_provider,
        document_ai_provider=provider_token,
        vision_page_images=vision_page_images,
    )

    if understand.can_understand:
        # Drop stale OCR / full-extract leftovers BEFORE vision persist so
        # posting fields (amounts, tax ids, line items) are not wiped after write.
        from app.config import get_settings
        from app.services.invoice.invoice_reset import (
            clear_stale_not_understood_for_understood_path,
            restore_prior_document_type_if_unmapped,
            restore_unrefilled_vision_stale_snapshot,
        )

        use_dt_scoped = bool(get_settings().vision_dt_scoped_extract)

        stale_clear: dict[str, object] = {}
        if not preserve_extracted_fields:
            stale_clear = await clear_stale_not_understood_for_understood_path(
                session,
                invoice,
                preserve_document_type=bool(human_locked_dt),
            )
        if (
            stale_clear.get("cleared_line_item_count")
            or stale_clear.get("cleared_document_type")
            or stale_clear.get("stripped_extracted_field_keys")
        ):
            # Audit omits bulky value snapshots (columns / extracted blobs).
            await log_event(
                session,
                "vision_path_stale_extract_cleared",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    cleared_line_item_count=stale_clear.get("cleared_line_item_count"),
                    cleared_document_type=stale_clear.get("cleared_document_type"),
                    stripped_extracted_field_keys=stale_clear.get(
                        "stripped_extracted_field_keys"
                    ),
                    prior_document_type_code=stale_clear.get("prior_document_type_code"),
                    snapshot_column_keys=sorted(
                        (stale_clear.get("column_snapshot") or {}).keys()
                    )
                    if isinstance(stale_clear.get("column_snapshot"), dict)
                    else [],
                    snapshot_extracted_keys=sorted(
                        (stale_clear.get("extracted_snapshot") or {}).keys()
                    )
                    if isinstance(stale_clear.get("extracted_snapshot"), dict)
                    else [],
                ),
            )

        from app.services.invoice.vision_document_type_map import (
            map_vision_label_to_document_type_with_llm_fallback,
        )
        from app.services.invoice.vision_header_extract import CANONICAL_DOCUMENT_TYPE_KEY
        from app.services.master_data.master_data_service import list_employee_masters
        from app.services.rule_book.rule_book_mapper import load_classification_config

        rb_config = await load_classification_config(session, invoice.tenant_id)
        # Employee registry needed before DT map so email/WhatsApp/Viber claims
        # resolve to Team Expenses even when vision titles look like retail receipts.
        te_employees = await list_employee_masters(
            session, invoice.tenant_id, include_advance_balances=False
        )
        enabled_dt_codes = {
            (dt.code or "").strip().upper()
            for dt in (rb_config.document_types or [])
            if getattr(dt, "enabled", True) and (dt.code or "").strip()
        }
        vendor_learning_key = resolve_vendor_learning_key(invoice)
        vision_few_shots = await few_shot_examples_for_tenant(
            session,
            tenant_id=invoice.tenant_id,
            valid_dt_codes=enabled_dt_codes,
            vendor_key=vendor_learning_key,
            vendor_limit=ai_cfg.vendor_few_shot_limit,
        )

        header = None
        dt_extract = None
        header_ok = False

        if use_dt_scoped:
            # type-suggest → DT map → DT-scoped extract
            type_suggest = await phase_vision_type_suggest(
                session,
                invoice,
                org=org,
                doc_provider=doc_provider,
                document_ai_provider=provider_token,
                vision_page_images=vision_page_images,
            )
            await session.flush()

            if not type_suggest.success and not human_locked_dt:
                await sync_vision_header_vault_path(
                    session, invoice, parsed_vendor=invoice.vendor
                )
                await session.flush()
                invoice.status = InvoiceStatus.EXCEPTION
                invoice.evaluation_status = EVAL_VISION_HEADER_REVIEW
                await log_event(
                    session,
                    "vision_path_pending",
                    invoice_id=invoice.id,
                    detail=audit_document_detail(
                        invoice,
                        reason="type_suggest_failed",
                        path=invoice.raw_file_path,
                        document_ai_provider=provider_token,
                        can_understand=True,
                        understand_confidence=understand.confidence,
                        evaluation_status=invoice.evaluation_status,
                    ),
                )
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return

            fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
            dt_map = await map_vision_label_to_document_type_with_llm_fallback(
                document_heading=invoice.document_heading or "",
                canonical_document_type=str(fields.get(CANONICAL_DOCUMENT_TYPE_KEY) or ""),
                document_types=rb_config.document_types or [],
                human_locked_dt=human_locked_dt or "",
                invoice=invoice,
                session=session,
                tenant_id=invoice.tenant_id,
                org=org,
                few_shots=vision_few_shots,
                vendor_key=vendor_learning_key,
                employees=te_employees,
            )
            if dt_map.reason != "human_locked" and dt_map.code:
                apply_document_type_to_invoice(
                    invoice,
                    code=dt_map.code,
                    confidence=dt_map.confidence,
                    llm_suggested_dt=dt_map.code if dt_map.method == "llm_catalogue_fallback" else None,
                    llm_confidence=dt_map.confidence
                    if dt_map.method == "llm_catalogue_fallback"
                    else None,
                )
            await log_event(
                session,
                "vision_document_type_mapped",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    code=dt_map.code,
                    confidence=dt_map.confidence,
                    heading_kind=dt_map.heading_kind,
                    reason=dt_map.reason,
                    method=dt_map.method,
                    rule_reason=dt_map.rule_reason,
                    llm_reasoning=dt_map.llm_reasoning,
                    runner_up_code=dt_map.runner_up_code,
                    runner_up_score=dt_map.runner_up_score,
                    document_heading=invoice.document_heading,
                    canonical_document_type=fields.get(CANONICAL_DOCUMENT_TYPE_KEY),
                    document_type_code=invoice.document_type_code,
                    vision_confidence=type_suggest.confidence,
                    overridden_dt=dt_map.runner_up_code,
                    overridden_dt_confidence=dt_map.runner_up_score,
                ),
            )
            if not (invoice.document_type_code or "").strip() and not human_locked_dt:
                dt_restore = restore_prior_document_type_if_unmapped(
                    invoice,
                    stale_clear,
                    preserve_document_type=False,
                )
                if dt_restore.get("restored"):
                    await log_event(
                        session,
                        "vision_document_type_restored_prior",
                        invoice_id=invoice.id,
                        detail=audit_document_detail(invoice, **dt_restore),
                    )
            await session.flush()

            if not (invoice.document_type_code or "").strip() and not human_locked_dt:
                from app.services.purchase.team_expense_route_policy import (
                    ensure_team_expenses_document_type,
                    should_apply_employee_channel_te_force,
                )

                # Safety net: employee-channel TE must not stop on empty DT map.
                # Same commercial-hint skip as DT map — do not re-force after a
                # content-based skip (employee matrix is not a second gate).
                if should_apply_employee_channel_te_force(invoice, te_employees):
                    te_defn = ensure_team_expenses_document_type(
                        invoice, rb_config.document_types
                    )
                    if te_defn is not None and (invoice.document_type_code or "").strip():
                        await log_event(
                            session,
                            "vision_document_type_mapped",
                            invoice_id=invoice.id,
                            detail=audit_document_detail(
                                invoice,
                                code=invoice.document_type_code,
                                confidence=invoice.document_type_confidence,
                                reason="employee_channel_forced",
                                method="te_employee_channel",
                                rule_reason="dt_map_unresolved_safety_net",
                                document_heading=invoice.document_heading,
                                canonical_document_type=fields.get(
                                    CANONICAL_DOCUMENT_TYPE_KEY
                                ),
                                document_type_code=invoice.document_type_code,
                            ),
                        )
                        await log_event(
                            session,
                            "vision_te_channel_forced",
                            invoice_id=invoice.id,
                            detail=audit_document_detail(
                                invoice,
                                decision="force",
                                authority="document_role_hints",
                                employee_channel_matched=True,
                                rule_reason="dt_map_unresolved_safety_net",
                                employee_sender=invoice.email_sender,
                            ),
                        )
                        await session.flush()
                if not (invoice.document_type_code or "").strip():
                    await sync_vision_header_vault_path(
                        session, invoice, parsed_vendor=invoice.vendor
                    )
                    await session.flush()
                    invoice.status = InvoiceStatus.EXCEPTION
                    invoice.evaluation_status = EVAL_VISION_HEADER_REVIEW
                    await log_event(
                        session,
                        "vision_path_pending",
                        invoice_id=invoice.id,
                        detail=audit_document_detail(
                            invoice,
                            reason="dt_map_unresolved",
                            path=invoice.raw_file_path,
                            document_ai_provider=provider_token,
                            can_understand=True,
                            understand_confidence=understand.confidence,
                            document_heading=invoice.document_heading,
                            evaluation_status=invoice.evaluation_status,
                        ),
                    )
                    send_notification(invoice, InvoiceStatus.EXCEPTION)
                    return

            posting_defn_early = None
            from app.services.invoice.vision_posting_continue import (
                resolve_vision_posting_definition,
            )

            posting_defn_early = resolve_vision_posting_definition(invoice, rb_config)
            dt_extract = await phase_vision_dt_extract(
                session,
                invoice,
                org=org,
                document_types=rb_config.document_types or [],
                confirmed_dt=invoice.document_type_code or "",
                doc_provider=doc_provider,
                document_ai_provider=provider_token,
                vision_page_images=vision_page_images,
                few_shots=vision_few_shots,
                definition=posting_defn_early,
                preserve_existing=preserve_extracted_fields,
                understand_confidence=understand.confidence,
            )
            # Safety net: if extract revealed link signals that prefer another DT,
            # flip once and re-extract (never when human-locked).
            if (
                not human_locked_dt
                and dt_extract.success
                and (invoice.document_type_code or "").strip()
            ):
                from app.services.invoice.vision_dt_reaffirm import (
                    rematch_document_type_after_extract,
                )

                prior_dt = (invoice.document_type_code or "").strip().upper()
                rematch = rematch_document_type_after_extract(
                    invoice=invoice,
                    document_types=rb_config.document_types or [],
                    heading_kind=dt_map.heading_kind,
                    current_code=prior_dt,
                )
                if rematch is not None and rematch.code:
                    apply_document_type_to_invoice(
                        invoice,
                        code=rematch.code,
                        confidence=rematch.confidence,
                    )
                    await log_event(
                        session,
                        "vision_document_type_reaffirmed",
                        invoice_id=invoice.id,
                        detail=audit_document_detail(
                            invoice,
                            prior_document_type_code=prior_dt,
                            document_type_code=rematch.code,
                            method=rematch.method,
                            reason=rematch.reason,
                            confidence=rematch.confidence,
                            heading_kind=rematch.heading_kind,
                            po_reference=getattr(invoice, "po_reference", None),
                            so_reference=getattr(invoice, "so_reference", None),
                        ),
                    )
                    await session.flush()
                    posting_defn_early = resolve_vision_posting_definition(
                        invoice, rb_config
                    )
                    dt_extract = await phase_vision_dt_extract(
                        session,
                        invoice,
                        org=org,
                        document_types=rb_config.document_types or [],
                        confirmed_dt=invoice.document_type_code or "",
                        doc_provider=doc_provider,
                        document_ai_provider=provider_token,
                        vision_page_images=vision_page_images,
                        few_shots=vision_few_shots,
                        definition=posting_defn_early,
                        preserve_existing=preserve_extracted_fields,
                        understand_confidence=understand.confidence,
                    )
            retained = restore_unrefilled_vision_stale_snapshot(invoice, stale_clear)
            if retained.get("restored_columns") or retained.get("restored_extracted_keys"):
                await log_event(
                    session,
                    "vision_path_stale_values_retained",
                    invoice_id=invoice.id,
                    detail=audit_document_detail(invoice, **retained),
                )
            await session.flush()
            header_ok = bool(dt_extract.success) and not bool(dt_extract.needs_review)
        else:
            # Legacy: fixed header extract → DT map
            header = await phase_vision_header_extract(
                session,
                invoice,
                org=org,
                doc_provider=doc_provider,
                document_ai_provider=provider_token,
                vision_page_images=vision_page_images,
                preserve_existing=preserve_extracted_fields,
            )
            retained = restore_unrefilled_vision_stale_snapshot(invoice, stale_clear)
            if retained.get("restored_columns") or retained.get("restored_extracted_keys"):
                await log_event(
                    session,
                    "vision_path_stale_values_retained",
                    invoice_id=invoice.id,
                    detail=audit_document_detail(invoice, **retained),
                )
            await session.flush()

            fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
            dt_map = await map_vision_label_to_document_type_with_llm_fallback(
                document_heading=invoice.document_heading or "",
                canonical_document_type=str(fields.get(CANONICAL_DOCUMENT_TYPE_KEY) or ""),
                document_types=rb_config.document_types or [],
                human_locked_dt=human_locked_dt or "",
                invoice=invoice,
                session=session,
                tenant_id=invoice.tenant_id,
                org=org,
                few_shots=vision_few_shots,
                vendor_key=vendor_learning_key,
                employees=te_employees,
            )
            if dt_map.reason != "human_locked" and dt_map.code:
                apply_document_type_to_invoice(
                    invoice,
                    code=dt_map.code,
                    confidence=dt_map.confidence,
                    llm_suggested_dt=dt_map.code if dt_map.method == "llm_catalogue_fallback" else None,
                    llm_confidence=dt_map.confidence
                    if dt_map.method == "llm_catalogue_fallback"
                    else None,
                )
            await log_event(
                session,
                "vision_document_type_mapped",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    code=dt_map.code,
                    confidence=dt_map.confidence,
                    heading_kind=dt_map.heading_kind,
                    reason=dt_map.reason,
                    method=dt_map.method,
                    rule_reason=dt_map.rule_reason,
                    llm_reasoning=dt_map.llm_reasoning,
                    runner_up_code=dt_map.runner_up_code,
                    runner_up_score=dt_map.runner_up_score,
                    document_heading=invoice.document_heading,
                    canonical_document_type=fields.get(CANONICAL_DOCUMENT_TYPE_KEY),
                    document_type_code=invoice.document_type_code,
                    vision_confidence=getattr(header, "confidence", None),
                    overridden_dt=dt_map.runner_up_code,
                    overridden_dt_confidence=dt_map.runner_up_score,
                ),
            )
            if not (invoice.document_type_code or "").strip() and not human_locked_dt:
                dt_restore = restore_prior_document_type_if_unmapped(
                    invoice,
                    stale_clear,
                    preserve_document_type=False,
                )
                if dt_restore.get("restored"):
                    await log_event(
                        session,
                        "vision_document_type_restored_prior",
                        invoice_id=invoice.id,
                        detail=audit_document_detail(invoice, **dt_restore),
                    )
            await session.flush()
            header_ok = bool(header.success) and not bool(getattr(header, "needs_review", False))

        from app.services.dossier.vision_bundle_linkage import apply_vision_bundle_on_hold
        from app.tenant_settings import tenant_custom_bundle_field_key

        async def _reprocess_po(anchor: str) -> None:
            await _maybe_reprocess_held_commercial_siblings(
                session,
                invoice,
                route_target=ROUTE_PURCHASE,
                anchor_ref=anchor,
            )

        async def _reprocess_so(anchor: str) -> None:
            await _maybe_reprocess_held_commercial_siblings(
                session,
                invoice,
                route_target=ROUTE_SALES,
                anchor_ref=anchor,
            )

        vision_link = await apply_vision_bundle_on_hold(
            session,
            invoice,
            custom_field_key=tenant_custom_bundle_field_key(tenant_row),
            reprocess_po_siblings=_reprocess_po,
            reprocess_so_siblings=_reprocess_so,
        )
        await session.flush()
        if vision_link.has_key:
            await log_event(
                session,
                "vision_bundle_linked",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    vision_bundle_kind=vision_link.kind,
                    vision_bundle_key=vision_link.key,
                    custom_field_key=vision_link.custom_field_key,
                ),
            )
        else:
            await log_event(
                session,
                "vision_bundle_standalone",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    vision_bundle_kind="none",
                    reason="no_linkage_key",
                ),
            )

        from app.services.invoice.vision_posting_continue import (
            continue_vision_understood_posting,
            resolve_vision_posting_definition,
            vision_hold_evaluation_status,
            vision_posting_skip_reason,
            vision_should_continue_posting,
        )
        from app.services.purchase.team_expense_route_policy import (
            apply_employee_channel_team_expenses_route,
            should_apply_employee_channel_te_force,
        )
        from app.services.extraction.line_item_extraction_policy import (
            team_expense_hard_requires_line_items,
        )

        # Known employee on email/WhatsApp/Viber must land on Team Expenses *before*
        # the posting gate — otherwise line_items_review on a wrong Expense Claim DT
        # skips continue and force-TE never runs. Reuse the registry loaded for DT map.
        employees = te_employees
        if should_apply_employee_channel_te_force(invoice, employees):
            apply_employee_channel_team_expenses_route(
                invoice, rb_config.document_types, employees
            )
            posting_defn = resolve_vision_posting_definition(invoice, rb_config)
            if (
                (invoice.evaluation_status or "").strip() == EVAL_LINE_ITEMS_REVIEW
                and not team_expense_hard_requires_line_items(
                    posting_defn,
                    team_expense_kind=getattr(invoice, "team_expense_kind", None),
                )
            ):
                invoice.evaluation_status = None
                if invoice.total is not None:
                    header_ok = True
            await session.flush()

        posting_defn = resolve_vision_posting_definition(invoice, rb_config)
        if vision_should_continue_posting(invoice, posting_defn, header_ok=header_ok):
            assert posting_defn is not None
            # Storage layout move is fine; catalogue route_target wins inside continue.
            await sync_vision_header_vault_path(
                session, invoice, parsed_vendor=invoice.vendor
            )
            await session.flush()
            from app.services.classification.document_type_catalog import (
                resolved_route_for_definition,
            )

            catalogue_route = resolved_route_for_definition(posting_defn)
            if catalogue_route:
                invoice.route_target = catalogue_route
            await continue_vision_understood_posting(
                session,
                invoice,
                config=rb_config,
                org=org,
                definition=posting_defn,
            )
            return

        skip_reason = vision_posting_skip_reason(
            invoice, posting_defn, header_ok=header_ok
        )
        await log_event(
            session,
            "vision_posting_skipped",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason=skip_reason,
                document_type_code=invoice.document_type_code,
                posting=(posting_defn.posting if posting_defn else None),
                header_ok=header_ok,
            ),
        )

        from app.services.invoice.vision_posting_continue import vision_should_sync_register

        # Supporting register docs (PO/GRN/SO/DN) have posting=No but must still
        # sync the purchase/sales register — never leave them as vision_vaulted.
        if skip_reason == "dt_not_posting" and vision_should_sync_register(posting_defn):
            assert posting_defn is not None
            await sync_vision_header_vault_path(
                session, invoice, parsed_vendor=invoice.vendor
            )
            await session.flush()
            if (posting_defn.route_target or "").strip():
                invoice.route_target = posting_defn.route_target
            from app.services.classification.document_type_playbook_service import (
                _infer_purchase_bundle_role,
                _infer_sales_bundle_role,
            )
            from app.models.invoice import PurchaseDocumentType, SalesDocumentType

            purchase_role = _infer_purchase_bundle_role(posting_defn)
            sales_role = _infer_sales_bundle_role(posting_defn)
            if purchase_role in {
                PurchaseDocumentType.PO.value,
                PurchaseDocumentType.GRN.value,
            }:
                invoice.purchase_document_type = purchase_role
                invoice.sales_document_type = None
            elif sales_role in {
                SalesDocumentType.SO.value,
                SalesDocumentType.DN.value,
            }:
                invoice.sales_document_type = sales_role
                invoice.purchase_document_type = None

            from app.services.invoice.pipeline import (
                _finish_purchase_supporting_document,
                _finish_sales_supporting_document,
            )

            if purchase_role in {
                PurchaseDocumentType.PO.value,
                PurchaseDocumentType.GRN.value,
            }:
                await _finish_purchase_supporting_document(session, invoice)
            else:
                await _finish_sales_supporting_document(session, invoice)
            await log_event(
                session,
                "vision_supporting_register_synced",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    reason="dt_not_posting_register_sync",
                    purchase_document_type=invoice.purchase_document_type,
                    sales_document_type=invoice.sales_document_type,
                ),
            )
            return

        # Vision-only vault layout: Unrouted/{type}/{vendor}/… (legacy sync untouched).
        moved = await sync_vision_header_vault_path(
            session, invoice, parsed_vendor=invoice.vendor
        )
        await session.flush()
        if not moved:
            await log_event(
                session,
                "vault_layout_sync_skipped",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    reason="vision_header_vault_sync_noop",
                    path=invoice.raw_file_path,
                    route_target=invoice.route_target,
                    vendor=invoice.vendor,
                    document_heading=invoice.document_heading,
                    canonical_document_type=(invoice.extracted_fields or {}).get(
                        "canonical_document_type"
                    ),
                ),
            )

        invoice.status = InvoiceStatus.EXCEPTION
        # Vault-only DTs (posting=No) vault cleanly even when money fields are
        # empty — Air Waybills etc. never post, so header review is wrong.
        invoice.evaluation_status = vision_hold_evaluation_status(
            invoice,
            posting_defn,
            header_ok=header_ok,
        )
        extract_success = (
            bool(dt_extract.success)
            if dt_extract is not None
            else bool(header.success if header is not None else False)
        )
        extract_confidence = (
            float(dt_extract.confidence)
            if dt_extract is not None
            else float(getattr(header, "confidence", 0.0) or 0.0)
        )
        extract_needs_review = (
            bool(dt_extract.needs_review)
            if dt_extract is not None
            else bool(getattr(header, "needs_review", False) if header is not None else False)
        )
        extract_page_count = (
            getattr(dt_extract, "page_count", None)
            if dt_extract is not None
            else getattr(header, "page_count", None) if header is not None else None
        )
        await log_event(
            session,
            "vision_path_pending",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason="bundled_and_vaulted",
                path=invoice.raw_file_path,
                document_ai_provider=provider_token,
                can_understand=True,
                understand_confidence=understand.confidence,
                header_success=extract_success,
                header_confidence=extract_confidence,
                header_needs_review=extract_needs_review,
                header_page_count=extract_page_count,
                dt_scoped_extract=use_dt_scoped,
                document_heading=invoice.document_heading,
                canonical_document_type=(invoice.extracted_fields or {}).get(
                    "canonical_document_type"
                ),
                invoice_no=invoice.invoice_no,
                po_reference=invoice.po_reference,
                so_reference=invoice.so_reference,
                vision_bundle_kind=vision_link.kind,
                vision_bundle_key=vision_link.key,
                vendor=invoice.vendor,
                invoice_date=invoice.invoice_date.isoformat()
                if invoice.invoice_date
                else None,
                total=str(invoice.total) if invoice.total is not None else None,
                currency=invoice.currency,
                evaluation_status=invoice.evaluation_status,
                posting_skip_reason=skip_reason,
            ),
        )
        # Understood path vault-only: do not emit routing_review_required
        # (that event fails dossier Validate with “confirm document type”).
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    try:
        await phase_image_quality(
            session,
            invoice,
            document_ai_provider=provider_token,
            vision_page_images=vision_page_images,
        )
        readiness = await phase_layout_readiness(
            session,
            invoice,
            document_ai_provider=provider_token,
        )
        ocr = await phase_ocr(
            session,
            invoice,
            org=org,
            document_types=config.document_types,
            doc_provider=doc_provider,
            provider_token=provider_token,
            human_locked_dt=human_locked_dt,
            vision_page_images=vision_page_images,
            readiness=readiness,
        )
    except OcrFailed as exc:
        reason = str(exc) or "ocr_failed"
        invoice.status = InvoiceStatus.EXCEPTION
        if reason == "image_quality_severe":
            invoice.evaluation_status = EVAL_NEEDS_RESCAN
            await log_event(
                session,
                "parsing_failed",
                invoice_id=invoice.id,
                detail=audit_document_detail(
                    invoice,
                    reason=reason,
                    document_ai_provider=provider_token,
                ),
            )
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "image_quality",
                    "review_reasons": [ReviewReason.IMAGE_QUALITY_LOW.value],
                    "document_ai_provider": provider_token,
                    "resubmit_hint": "Please resend a flat, well-lit scan or PDF.",
                },
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return
        if human_locked_dt:
            invoice.evaluation_status = EVAL_NEEDS_REVIEW
        else:
            invoice.evaluation_status = EVAL_AWAITING_CLASSIFICATION
        await log_event(
            session,
            "parsing_failed",
            invoice_id=invoice.id,
            detail=audit_document_detail(
                invoice,
                reason="ocr_failed",
                error=str(exc),
                document_ai_provider=provider_token,
            ),
        )
        if not human_locked_dt:
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "classification",
                    "review_reasons": [ReviewReason.PROVIDER_UNAVAILABLE.value],
                    "document_ai_provider": provider_token,
                    "provider_unavailable": True,
                },
            )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    quality_result = await phase_ocr_quality_confirm(
        session,
        invoice,
        ocr=ocr,
        ai_cfg=ai_cfg,
        document_ai_provider=provider_token,
    )
    if not quality_result.passed:
        if should_skip(invoice, "image_quality"):
            await _log_processing_override_skip(session, invoice, "image_quality")
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            invoice.evaluation_status = EVAL_NEEDS_RESCAN
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "ocr_quality_confirm",
                    "review_reasons": quality_result.review_reasons,
                    "text_length": quality_result.text_length,
                    "sparse": quality_result.sparse,
                    "min_text_chars": quality_result.min_text_chars,
                    "document_ai_provider": provider_token,
                    "resubmit_hint": "Please resend a flat, well-lit scan or PDF.",
                },
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    from app.services.dossier.document_duplicate_service import (
        refresh_duplicate_review_after_ocr,
    )
    from app.services.extraction.document_identity_service import (
        identity_field_keys_from_catalogue,
    )

    await refresh_duplicate_review_after_ocr(
        session,
        invoice,
        ocr_text=ocr.text,
        custom_field_keys=identity_field_keys_from_catalogue(config.document_types),
    )

    from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
    from app.services.invoice.processing_override_catalog import consume_deferred_full_reset

    if consume_deferred_full_reset(invoice) and not preserve_extracted_fields:
        keep_dt = bool(human_locked_dt) or (
            classification_override and bool(locked_dt_code)
        ) or "classification" in skip_steps_for(invoice)
        await reset_invoice_for_reprocess(
            session,
            invoice,
            preserve_document_type=keep_dt,
            clear_overrides=False,
        )
        await session.flush()

    enabled_dt_codes = {
        (dt.code or "").strip().upper()
        for dt in config.document_types
        if dt.enabled and (dt.code or "").strip()
    }
    vendor_learning_key = resolve_vendor_learning_key(invoice)
    few_shots = await few_shot_examples_for_tenant(
        session,
        tenant_id=invoice.tenant_id,
        valid_dt_codes=enabled_dt_codes,
        vendor_key=vendor_learning_key,
        vendor_limit=ai_cfg.vendor_few_shot_limit,
    )

    if not skip_classify_gate:
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as path:
            classify_llm = await phase_llm_classify(
                session,
                invoice,
                ocr=ocr,
                org=org,
                document_types=config.document_types,
                few_shots=few_shots,
                doc_provider=doc_provider,
                provider_token=provider_token,
                file_path=path,
                vision_page_images=vision_page_images,
            )
            if classify_llm is not None:
                persist_llm_party_context(invoice, classify_llm, org)
                await session.flush()

        vendor_drift_result = await check_vendor_classification_drift(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            vendor_key=vendor_learning_key,
            classify_llm=classify_llm,
            ai_cfg=ai_cfg,
        )
        if vendor_drift_result is not None:
            await log_event(
                session,
                "vendor_classification_drift"
                if vendor_drift_result.detected
                else "vendor_classification_baseline",
                invoice_id=invoice.id,
                detail=drift_audit_detail(vendor_drift_result),
            )

        classify_llm, heading_reconcile_detail = reconcile_llm_dt_with_heading(
            classify_llm,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
        )
        if heading_reconcile_detail:
            invoice.llm_suggested_dt = (classify_llm.suggested_dt if classify_llm else None) or None
            if classify_llm is not None:
                invoice.llm_confidence = round(classify_llm.confidence, 4)
            await log_event(
                session,
                "classification_heading_reconcile",
                invoice_id=invoice.id,
                detail=heading_reconcile_detail,
            )

        classify_llm, policy_backfill_detail = backfill_llm_dt_from_policy(
            classify_llm,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
        )
        if policy_backfill_detail:
            invoice.llm_suggested_dt = (classify_llm.suggested_dt if classify_llm else None) or None
            if classify_llm is not None:
                invoice.llm_confidence = round(classify_llm.confidence, 4)
            await log_event(
                session,
                "classification_policy_backfill",
                invoice_id=invoice.id,
                detail=policy_backfill_detail,
            )

        gate_result = evaluate_confidence_gate(
            classify_llm,
            document_types=config.document_types,
            ai_cfg=ai_cfg,
            provider_token=provider_token,
        )
        gate_result = apply_recognition_mode_gate(
            gate_result,
            invoice=invoice,
            ocr=ocr,
            document_types=config.document_types,
        )

        await log_event(
            session,
            "classification_gate_passed" if gate_result.passed else "classification_gate_failed",
            invoice_id=invoice.id,
            detail=gate_audit_detail(gate_result, provider_token=provider_token),
        )

        if not gate_result.passed:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            loaded.document_type_code = None
            loaded.document_type_confidence = None
            invoice.document_type_code = None
            invoice.document_type_confidence = None
            loaded.evaluation_status = EVAL_AWAITING_CLASSIFICATION
            invoice.evaluation_status = EVAL_AWAITING_CLASSIFICATION
            loaded.llm_suggested_dt = invoice.llm_suggested_dt
            loaded.llm_confidence = invoice.llm_confidence
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "classification",
                    "compare_passed": False,
                    "document_type_code": None,
                    "document_type_confidence": None,
                    "route_target": None,
                    "review_reasons": gate_result.review_reasons,
                    "llm_suggested_dt": gate_result.llm_suggested_dt,
                    "llm_confidence": gate_result.llm_confidence,
                    "llm_reasoning": gate_result.llm_reasoning,
                    "min_route_confidence": gate_result.min_route_confidence,
                    "org_auto_route_min_confidence": gate_result.org_auto_route_min_confidence,
                    "dt_min_route_confidence": gate_result.dt_min_route_confidence,
                    "document_ai_provider": provider_token,
                },
            )
            from app.services.classification.classification_gap_event import (
                build_classification_gap_event,
                gap_event_audit_detail,
            )

            gap_event = build_classification_gap_event(
                org_id=str(invoice.tenant_id),
                invoice_id=invoice.id,
                ocr_text=ocr.text or "",
                candidates=[
                    {
                        "code": gate_result.llm_suggested_dt,
                        "confidence": gate_result.llm_confidence,
                    }
                ],
                chosen_dt=gate_result.confirmed_dt or gate_result.llm_suggested_dt or "",
            )
            await log_event(
                session,
                "classification_gap_event",
                invoice_id=invoice.id,
                detail=gap_event_audit_detail(gap_event),
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

        confirmed_dt = gate_result.confirmed_dt

    if skip_classify_gate and (human_locked_dt or classification_override):
        override_dt = locked_dt_code if classification_override and not human_locked_dt else human_locked_dt
        if classification_override and not human_locked_dt:
            await _log_processing_override_skip(session, invoice, "classification")
        await log_event(
            session,
            "llm_classified",
            invoice_id=invoice.id,
            detail={
                "llm_suggested_dt": override_dt,
                "llm_confidence": float(invoice.document_type_confidence or 0.95),
                "skipped": True,
                "human_locked": bool(human_locked_dt),
                "processing_override": classification_override and not human_locked_dt,
                "document_ai_provider": provider_token,
            },
        )
        await log_event(
            session,
            "classification_gate_passed",
            invoice_id=invoice.id,
            detail={
                "human_locked": bool(human_locked_dt),
                "processing_override": classification_override and not human_locked_dt,
                "confirmed_dt": override_dt,
                "confirmed_confidence": float(invoice.document_type_confidence or 0.95),
                "document_ai_provider": provider_token,
            },
        )

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

    if classify_llm is not None:
        loaded.llm_suggested_dt = invoice.llm_suggested_dt
        loaded.llm_confidence = invoice.llm_confidence

    with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as local_path:
        extract_result = await extract_fields(
            ocr,
            file_path=local_path,
            org=org,
            document_types=config.document_types,
            confirmed_dt=confirmed_dt,
            few_shots=few_shots,
            provider=doc_provider,
            vision_page_images=vision_page_images,
        )
    if extract_result.di_enrich_detail:
        await log_event(
            session,
            "di_route_enrich",
            invoice_id=invoice.id,
            detail=extract_result.di_enrich_detail,
        )
    llm_result = extract_result.llm
    ocr = extract_result.ocr
    if invoice.file_hash and (
        (ocr.payload_json or {}).get("invoice_fields")
        or (ocr.payload_json or {}).get("extraction_route")
        or (ocr.payload_json or {}).get("finance_document")
        or (ocr.payload_json or {}).get("di_line_items")
    ):
        from app.services.classification.classification_learning_service import (
            upsert_ocr_artifact_enrichment,
        )

        await upsert_ocr_artifact_enrichment(
            session,
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            file_hash=invoice.file_hash,
            ocr=ocr,
        )
    from dataclasses import replace

    from app.services.extraction.extraction_field_values import (
        apply_parsed_extraction_fields,
        effective_extraction_field_keys_for_dt,
        enrich_parsed_from_ocr,
        ensure_extraction_baseline,
        non_canonical_extraction_keys,
    )
    from app.services.extraction.field_grounding_service import ground_parsed_fields
    from app.services.extraction.gap_fill_extraction_service import apply_extraction_gap_fill
    from app.services.extraction.pdf_parser import parse_local_text

    selected_keys = effective_extraction_field_keys_for_dt(config.document_types, confirmed_dt)
    custom_keys = non_canonical_extraction_keys(selected_keys)
    dt_definition = get_document_type_definition(
        confirmed_dt,
        document_types=config.document_types,
        tenant_id=invoice.tenant_id,
    )
    citation_results: list = []
    if llm_result is not None:
        from app.config import get_settings as _get_settings

        _settings = _get_settings()
        if _settings.use_citation_grounding:
            from app.services.extraction.citation_grounding_service import (
                verify_and_apply_citations,
            )

            scalar_citation_keys = [
                key for key in selected_keys if str(key).strip().lower() != "line_items"
            ]
            llm_result, citation_results = verify_and_apply_citations(
                llm_result,
                ocr,
                field_keys=scalar_citation_keys,
            )
        if _settings.use_extraction_self_consistency:
            from app.services.extraction.llm_document_service import extract_document_fields
            from app.services.extraction.self_consistency_service import run_self_consistency

            llm_result, consistency_outcomes = await run_self_consistency(
                base_result=llm_result,
                ocr=ocr,
                dt_definition=dt_definition,
                extract_fn=extract_document_fields,
                extract_kwargs={
                    "ocr": ocr,
                    "org": org,
                    "document_types": config.document_types,
                    "confirmed_dt": confirmed_dt,
                    "few_shots": few_shots,
                },
                use_citation_grounding=_settings.use_citation_grounding,
            )
            disagreements = {
                key: value
                for key, value in consistency_outcomes.items()
                if not value.get("agreed")
            }
            if disagreements:
                await log_event(
                    session,
                    "self_consistency_disagreement",
                    invoice_id=invoice.id,
                    detail={"fields": disagreements},
                )
    if llm_result is not None:
        from app.services.classification.playbook_profile_catalog import (
            effective_counterparty_source,
        )

        parsed = llm_result_to_invoice_data(
            llm_result,
            ocr=ocr,
            custom_keys=custom_keys or None,
            selected_keys=selected_keys,
            org=org,
            counterparty_source=effective_counterparty_source(dt_definition)
            if dt_definition
            else "letterhead",
            route_target=dt_definition.route_target if dt_definition else None,
        )
        persist_llm_party_context(invoice, llm_result, org)
    else:
        local = parse_local_text(ocr.text or "")
        parsed = replace(local, document_text=ocr.text or local.document_text)
    from app.config import get_settings as _trace_settings
    from app.services.extraction.line_item_trace import resolve_line_item_trace

    line_item_trace = resolve_line_item_trace(_trace_settings().runtime_line_item_trace_enabled)
    parsed = ground_parsed_fields(
        parsed,
        ocr.text,
        selected_keys,
        ocr.payload_json,
        trace=line_item_trace,
        org_country=org.country if org else None,
    )
    parsed = enrich_parsed_from_ocr(parsed, ocr, dt_definition=dt_definition, trace=line_item_trace)

    from app.config import get_settings as _telemetry_settings
    from app.services.extraction.field_resolution_telemetry import detail_from_parsed_telemetry

    if _telemetry_settings().log_field_resolution_telemetry:
        telemetry_detail = detail_from_parsed_telemetry(parsed)
        if telemetry_detail:
            if isinstance(telemetry_detail, dict):
                telemetry_detail = {
                    **telemetry_detail,
                    "document_ai_provider": provider_token,
                }
            await log_event(
                session,
                "field_resolution_telemetry",
                invoice_id=invoice.id,
                detail=telemetry_detail,
            )

    parsed, gap_fill_detail = await apply_extraction_gap_fill(
        parsed,
        ocr=ocr,
        selected_keys=selected_keys,
        org=org,
        dt_definition=dt_definition,
        invoice=loaded,
    )
    if gap_fill_detail.get("gap_fill_attempted"):
        await log_event(
            session,
            "extraction_gap_fill",
            invoice_id=invoice.id,
            detail=gap_fill_detail,
        )

    from app.services.extraction.currency_detection_service import apply_currency_detection

    parsed, currency_detect_detail = await apply_currency_detection(
        parsed,
        ocr=ocr,
        org=org,
        selected_keys=selected_keys,
        dt_definition=dt_definition,
    )
    if currency_detect_detail.get("currency_detect_attempted"):
        await log_event(
            session,
            "currency_detection",
            invoice_id=invoice.id,
            detail=currency_detect_detail,
        )

    from app.services.extraction.line_items_fallback_service import apply_line_items_fallback

    parsed, fallback_tier = apply_line_items_fallback(
        parsed,
        ocr_text=ocr.text,
        ocr_payload=ocr.payload_json or {},
        dt_definition=dt_definition,
    )
    if fallback_tier:
        await log_event(
            session,
            "line_items_fallback_applied",
            invoice_id=invoice.id,
            detail={"tier": fallback_tier, "line_count": len(parsed.line_items or [])},
        )

    if llm_result is not None:
        from app.config import get_settings as _get_settings

        _settings = _get_settings()
        if _settings.use_citation_grounding and "line_items" in {
            str(key).strip().lower() for key in selected_keys
        }:
            from app.services.extraction.citation_grounding_service import (
                citation_audit_detail,
                verify_parsed_line_items_citation,
            )

            line_items_result = verify_parsed_line_items_citation(
                list(parsed.line_items or []),
                ocr_text=ocr.text or "",
                ocr_payload=ocr.payload_json or {},
            )
            citation_results = list(citation_results) + [line_items_result]
        if llm_result is not None and _settings.use_citation_grounding and citation_results:
            from app.services.extraction.citation_grounding_service import citation_audit_detail

            await log_event(
                session,
                "citation_grounding",
                invoice_id=invoice.id,
                detail=citation_audit_detail(citation_results),
            )
            citation_detail = citation_audit_detail(citation_results)
            if citation_detail.get("citation_failed") and flag_enabled_for_dt(
                "use_citation_grounding",
                confirmed_dt,
                tenant_id=invoice.tenant_id,
            ):
                loaded.evaluation_status = EVAL_NEEDS_REVIEW
                invoice.evaluation_status = EVAL_NEEDS_REVIEW
                await log_event(
                    session,
                    "routing_review_required",
                    invoice_id=invoice.id,
                    detail={
                        "gate": "citation_grounding",
                        "review_reasons": ["citation_failed"],
                        "citation_failed": citation_detail.get("citation_failed"),
                    },
                )

    field_conf_result = evaluate_field_confidence_gate(
        llm_result,
        ai_cfg=ai_cfg,
        dt_definition=dt_definition,
        parsed=parsed,
        invoice=loaded,
        confirmed_dt=confirmed_dt,
        ocr_payload=dict(ocr.payload_json or {}) if ocr else None,
    )
    await log_event(
        session,
        "field_confidence_evaluated",
        invoice_id=invoice.id,
        detail=field_confidence_audit_detail(field_conf_result),
    )

    from app.services.classification.document_type_playbook_service import confidence_gate_fields
    from app.services.invoice.invoice_pipeline_phases import evaluate_line_item_review_gate

    li_passed, li_confidence, li_reasons = evaluate_line_item_review_gate(
        parsed,
        dt_definition=dt_definition,
    )
    if not li_passed:
        reasons = list(li_reasons or [])
        if "line_items_missing" in reasons:
            loaded.evaluation_status = EVAL_LINE_ITEMS_REVIEW
            invoice.evaluation_status = EVAL_LINE_ITEMS_REVIEW
            loaded.status = InvoiceStatus.EXCEPTION
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "line_items_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "line_items_missing",
                    "review_reasons": reasons,
                    "line_items_confidence": li_confidence,
                    "fallback_tier": fallback_tier,
                },
            )
        elif "line_items" in confidence_gate_fields(dt_definition):
            loaded.evaluation_status = EVAL_NEEDS_REVIEW
            invoice.evaluation_status = EVAL_NEEDS_REVIEW
            await log_event(
                session,
                "routing_review_required",
                invoice_id=invoice.id,
                detail={
                    "gate": "line_item_confidence",
                    "line_items_confidence": li_confidence,
                    "review_reasons": reasons,
                },
            )

    if _trace_settings().runtime_line_item_trace_enabled and line_item_trace.entries:
        raw_fields = dict(parsed.raw_fields or {})
        raw_fields["_line_item_trace"] = line_item_trace.to_dict()
        parsed = replace(parsed, raw_fields=raw_fields)

    from app.services.invoice.due_date_defaults import apply_due_on_receipt_to_parsed

    apply_due_on_receipt_to_parsed(parsed, dt_definition)

    resolved_vendor = await _apply_parsed_to_invoice(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        config=config,
        preserve_existing=preserve_extracted_fields,
        org=org,
        trace=line_item_trace,
    )

    if preserve_extracted_fields:
        parsed = invoice_data_from_invoice(loaded)

    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()

    await log_event(
        session,
        "parse_completed",
        invoice_id=invoice.id,
        detail={
            "source": provider_token,
            "confidence": "high" if not ocr.sparse else "low",
            "text_length": ocr.text_length,
            "di_model": ocr.di_model,
            "document_ai_provider": provider_token,
            "confirmed_dt": confirmed_dt,
            "extracted_snapshot": {
                "vendor": loaded.vendor,
                "invoice_no": loaded.invoice_no,
                "total": str(loaded.total) if loaded.total is not None else None,
                "subtotal": str(loaded.subtotal) if loaded.subtotal is not None else None,
                "gst": str(loaded.gst) if loaded.gst is not None else None,
                "abn": loaded.abn,
            },
        },
    )

    if human_locked_dt:
        apply_document_type_to_invoice(
            loaded,
            code=human_locked_dt,
            confidence=0.95,
            llm_suggested_dt=classify_llm.suggested_dt if classify_llm else None,
            llm_confidence=classify_llm.confidence if classify_llm else None,
        )
        await log_event(
            session,
            "document_classified",
            invoice_id=invoice.id,
            detail={
                "human_locked": True,
                "confirmed_dt": human_locked_dt,
                "llm_suggested_dt": classify_llm.suggested_dt if classify_llm else None,
                "llm_confidence": classify_llm.confidence if classify_llm else None,
                "document_ai_provider": provider_token,
                "extract_phase": True,
            },
        )
    elif gate_result is not None and gate_result.passed:
        apply_document_type_to_invoice(
            loaded,
            code=gate_result.confirmed_dt,
            confidence=gate_result.confirmed_confidence,
            llm_suggested_dt=gate_result.llm_suggested_dt,
            llm_confidence=gate_result.llm_confidence,
        )
        if llm_result is not None:
            loaded.llm_suggested_dt = llm_result.suggested_dt or gate_result.llm_suggested_dt
            loaded.llm_confidence = round(llm_result.confidence, 4)
        await log_event(
            session,
            "document_classified",
            invoice_id=invoice.id,
            detail={
                **gate_audit_detail(gate_result, provider_token=provider_token),
                "extract_phase": True,
            },
        )

    invoice.document_type_code = loaded.document_type_code
    invoice.document_type_confidence = loaded.document_type_confidence
    invoice.llm_suggested_dt = loaded.llm_suggested_dt
    invoice.llm_confidence = loaded.llm_confidence

    from app.services.invoice.invoice_post_classification_phases import (
        apply_policy_scorer_after_extract,
        reextract_fields_for_corrected_dt,
    )

    policy_result = await apply_policy_scorer_after_extract(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        config=config,
        llm_dt=(loaded.document_type_code or confirmed_dt or "").strip().upper(),
        llm_confidence=float(
            loaded.document_type_confidence
            or (gate_result.confirmed_confidence if gate_result is not None else 0.0)
        ),
        force=True,
        allow_auto_correct=True,
        auto_correct_gap=ai_cfg.policy_auto_correct_gap,
        review_gap=ai_cfg.policy_review_gap,
    )

    if policy_result.auto_corrected and policy_result.corrected_dt:
        confirmed_dt = policy_result.corrected_dt
        with open_pdf_for_reading(invoice.raw_file_path, tenant_id=invoice.tenant_id) as local_path:
            parsed, pruned_keys = await reextract_fields_for_corrected_dt(
                session,
                invoice=invoice,
                loaded=loaded,
                ocr=ocr,
                file_path=str(local_path),
                org=org,
                config=config,
                confirmed_dt=confirmed_dt,
                few_shots=few_shots,
                doc_provider=doc_provider,
                vision_page_images=vision_page_images,
            )
        policy_result.pruned_field_keys = pruned_keys
        # Second policy pass: hold on disagreement; never re-extract again.
        policy_verify = await apply_policy_scorer_after_extract(
            session,
            invoice=invoice,
            loaded=loaded,
            parsed=parsed,
            config=config,
            llm_dt=confirmed_dt,
            llm_confidence=float(
                loaded.document_type_confidence or policy_result.policy_confidence or 0.0
            ),
            force=True,
            allow_auto_correct=False,
            auto_correct_gap=ai_cfg.policy_auto_correct_gap,
            review_gap=ai_cfg.policy_review_gap,
        )
        if policy_verify.oscillation_hold or policy_verify.needs_review:
            invoice.status = InvoiceStatus.EXCEPTION
            invoice.evaluation_status = EVAL_NEEDS_REVIEW
            loaded.evaluation_status = EVAL_NEEDS_REVIEW
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=config,
        org=org,
    )
    invoice.vendor = loaded.vendor
    invoice.evaluation_status = loaded.evaluation_status
    invoice.route_target = loaded.route_target
    invoice.matched_rule_ids = loaded.matched_rule_ids
    invoice.vendor_confidence = loaded.vendor_confidence
    await _clear_purchase_awaiting_po_if_overridden(session, invoice, loaded)
    await _clear_sales_awaiting_so_if_overridden(session, invoice, loaded)

    dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))
    skip_field_conf_review = False
    if dt_definition is not None:
        from app.services.classification.document_type_playbook_profile_service import effective_approval_policy

        skip_field_conf_review = effective_approval_policy(dt_definition).mode == "no_posting"

    if (
        not field_conf_result.passed
        and not bypass_review_gates
        and not skip_field_conf_review
        and not should_skip(invoice, "field_confidence")
        and not _counterparty_registration_pending(loaded)
    ):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "field_confidence",
                "review_reasons": field_conf_result.review_reasons,
                "low_confidence_fields": field_conf_result.low_confidence_fields,
                "min_field_extract_confidence": field_conf_result.min_confidence,
            },
        )
    elif (
        not field_conf_result.passed
        and should_skip(invoice, "field_confidence")
    ):
        await _log_processing_override_skip(session, invoice, "field_confidence")
    elif vendor_drift_result is not None and vendor_drift_result.detected and not bypass_review_gates and not should_skip(invoice, "vendor_drift") and not _counterparty_registration_pending(loaded):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "vendor_classification_drift",
                "review_reasons": vendor_drift_result.review_reasons,
                **drift_audit_detail(vendor_drift_result),
            },
        )
    elif (
        vendor_drift_result is not None
        and vendor_drift_result.detected
        and should_skip(invoice, "vendor_drift")
    ):
        await _log_processing_override_skip(session, invoice, "vendor_drift")

    from app.services.purchase.purchase_document_service import apply_purchase_document_type_after_eval

    await apply_purchase_document_type_after_eval(session, loaded)
    from app.services.sales.sales_document_service import apply_sales_document_type_after_eval

    await apply_sales_document_type_after_eval(session, loaded)

    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug
    invoice.route_target = loaded.route_target

    parsed = ensure_extraction_baseline(loaded, parsed, ocr=ocr)

    from app.services.extraction.field_translation_service import apply_field_translation

    parsed, translation_detail = await apply_field_translation(
        parsed,
        context_text=ocr.text or parsed.document_text or "",
        path="not_understood",
    )
    if translation_detail.get("field_translation_attempted") or translation_detail.get(
        "field_translation_applied"
    ):
        await log_event(
            session,
            "field_translation",
            invoice_id=invoice.id,
            detail=translation_detail,
        )

    apply_parsed_extraction_fields(loaded, parsed)
    invoice.extracted_fields = loaded.extracted_fields
    invoice.so_reference = loaded.so_reference
    invoice.document_text = loaded.document_text
    invoice.email_attachment_name = loaded.email_attachment_name

    if dt_definition is None:
        dt_definition = resolve_definition_for_invoice(loaded, list(config.document_types))

    from app.services.invoice.invoice_post_classification_phases import evaluate_playbook_with_reextract

    playbook = await evaluate_playbook_with_reextract(
        session,
        invoice=invoice,
        loaded=loaded,
        parsed=parsed,
        definition=dt_definition,
        document_types=list(config.document_types),
        ocr=ocr,
        file_path=invoice.raw_file_path,
        org=org,
        config=config,
        confirmed_dt=confirmed_dt,
        few_shots=few_shots,
        doc_provider=doc_provider,
    )
    await log_event(
        session,
        "playbook_evaluated",
        invoice_id=invoice.id,
        detail={
            **playbook.audit_detail(),
            **(
                playbook_policy_audit_detail(dt_definition)
                if dt_definition is not None
                else {}
            ),
        },
    )
    if (
        requires_playbook_review(playbook, definition=dt_definition)
        and not bypass_review_gates
        and not should_skip(invoice, "playbook")
    ):
        loaded.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        invoice.status = InvoiceStatus.EXCEPTION
        from app.services.classification.document_type_playbook_service import (
            suggest_reclassify_direct_expense_code,
        )

        suggest_dt = suggest_reclassify_direct_expense_code(
            playbook,
            dt_definition,
            list(config.document_types),
        )
        await log_event(
            session,
            "routing_review_required",
            invoice_id=invoice.id,
            detail={
                "gate": "playbook",
                "document_type_code": loaded.document_type_code,
                "document_type_confidence": loaded.document_type_confidence,
                "route_target": invoice.route_target,
                "review_reasons": (
                    gate_result.review_reasons if gate_result else []
                ),
                "playbook": playbook.audit_detail(),
                "suggest_reclassify_dt": suggest_dt,
                **(
                    playbook_policy_audit_detail(dt_definition)
                    if dt_definition is not None
                    else {}
                ),
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    elif requires_playbook_review(playbook, definition=dt_definition) and should_skip(
        invoice, "playbook"
    ):
        await _log_processing_override_skip(session, invoice, "playbook")

    await _post_parse_relocate(session, loaded, resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.storage_vendor_slug = loaded.storage_vendor_slug

    if (loaded.route_target or "").strip() == ROUTE_PURCHASE:
        from app.services.purchase.purchase_document_service import sync_purchase_document

        await sync_purchase_document(session, loaded)
        invoice.purchase_document_type = loaded.purchase_document_type
        invoice.po_reference = loaded.po_reference
        invoice.evaluation_status = loaded.evaluation_status
        from app.services.invoice.invoice_post_classification_phases import log_match_phase_evaluated

        await log_match_phase_evaluated(
            session,
            invoice_id=invoice.id,
            detail={
                "route": "purchase",
                "evaluation_status": loaded.evaluation_status,
                "po_reference": loaded.po_reference,
                "purchase_document_type": loaded.purchase_document_type,
            },
        )
        if loaded.status == InvoiceStatus.EXCEPTION:
            purchase_hold_bypass = bypass_review_gates or override_bypasses_purchase_hold(invoice)
            if purchase_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
                from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

                if loaded.evaluation_status == EVAL_AWAITING_PO:
                    if override_bypasses_purchase_hold(invoice) and not bypass_review_gates:
                        await _log_processing_override_skip(session, invoice, "playbook")
                    loaded.evaluation_status = EVAL_AUTO_CODED
                    invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.PARSING
                invoice.status = InvoiceStatus.PARSING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                return

    if (loaded.route_target or "").strip() == ROUTE_SALES:
        from app.services.sales.sales_document_service import EVAL_AWAITING_SO, sync_sales_document

        await sync_sales_document(session, loaded)
        invoice.sales_document_type = loaded.sales_document_type
        invoice.so_reference = loaded.so_reference
        invoice.evaluation_status = loaded.evaluation_status
        from app.services.invoice.invoice_post_classification_phases import log_match_phase_evaluated

        await log_match_phase_evaluated(
            session,
            invoice_id=invoice.id,
            detail={
                "route": "sales",
                "evaluation_status": loaded.evaluation_status,
                "so_reference": loaded.so_reference,
                "sales_document_type": loaded.sales_document_type,
            },
        )
        if loaded.status == InvoiceStatus.EXCEPTION:
            sales_hold_bypass = bypass_review_gates or override_bypasses_sales_hold(invoice)
            if sales_hold_bypass:
                from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED

                if loaded.evaluation_status == EVAL_AWAITING_SO:
                    if override_bypasses_sales_hold(invoice) and not bypass_review_gates:
                        await _log_processing_override_skip(session, invoice, "playbook")
                    loaded.evaluation_status = EVAL_AUTO_CODED
                    invoice.evaluation_status = EVAL_AUTO_CODED
                loaded.status = InvoiceStatus.PARSING
                invoice.status = InvoiceStatus.PARSING
            else:
                invoice.status = InvoiceStatus.EXCEPTION
                return

    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.VALIDATING
    await session.flush()
    doc_type = loaded.purchase_document_type
    from app.services.classification.document_type_validation_service import PROFILE_STANDARD

    validation_profile = (
        PROFILE_STANDARD
        if not (loaded.document_type_code or "").strip()
        else None
    )
    results = await run_all_validations(
        parsed,
        session,
        invoice.id,
        tenant_id=invoice.tenant_id,
        sender=invoice.email_sender,
        route_target=invoice.route_target,
        purchase_document_type=doc_type,
        has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
        document_type_code=loaded.document_type_code,
        document_types=list(config.document_types),
        validation_profile=validation_profile,
        playbook_gates=playbook,
        invoice=loaded,
    )
    invoice.validation_results = results_to_json(results)
    invoice.abn = parsed.abn
    if not all_passed(results):
        if bypass_review_gates and human_approval_may_bypass_validation(results):
            await log_event(
                session,
                "validation_bypassed_after_human_approval",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
        elif should_skip(invoice, "validation"):
            await _log_processing_override_skip(session, invoice, "validation")
            await log_event(
                session,
                "validation_bypassed_processing_override",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
        else:
            stmt = (
                select(Invoice)
                .where(Invoice.id == invoice.id)
                .options(selectinload(Invoice.line_items))
            )
            loaded = (await session.execute(stmt)).scalar_one()
            await _sync_counterparty_and_evaluate(
                session,
                loaded,
                parsed=parsed,
                config=config,
                org=org,
            )
            await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
            invoice.raw_file_path = loaded.raw_file_path
            invoice.route_target = loaded.route_target
            if await _vendor_hold_unless_skipped(session, loaded):
                invoice.status = InvoiceStatus.EXCEPTION
                send_notification(invoice, InvoiceStatus.EXCEPTION)
                return
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "validation_failed",
                invoice_id=invoice.id,
                detail=validation_audit_detail(
                    results,
                    route_target=invoice.route_target,
                    has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
                ),
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    await log_event(
        session,
        "validation_passed",
        invoice_id=invoice.id,
        detail=validation_audit_detail(
            results,
            route_target=invoice.route_target,
            has_receipt_file=has_receipt_attachment(invoice.raw_file_path),
        ),
    )

    if await apply_document_type_approval_gate(
        session,
        invoice,
        definition=dt_definition,
        validation_results=results,
        human_approval_bypass=bypass_review_gates,
    ):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    if (invoice.route_target or "").strip() == ROUTE_VAULT:
        _mark_invoice_processed(invoice)
        # Archive route: never leave needs_review — no GL / rule-book coding applies.
        invoice.evaluation_status = EVAL_STATUS_AUTO_CODED
        loaded.evaluation_status = EVAL_STATUS_AUTO_CODED
        await log_event(
            session,
            "vault_stored",
            invoice_id=invoice.id,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
            },
        )
        send_notification(invoice, InvoiceStatus.PROCESSED)
        return

    if doc_type in ("po", "grn") and not bypass_review_gates:
        await _finish_purchase_supporting_document(session, invoice)
        return

    sales_doc_type = (loaded.sales_document_type or invoice.sales_document_type or "").strip().lower()
    if (
        sales_doc_type in ("so", "dn")
        and (invoice.route_target or "").strip() == ROUTE_SALES
        and not bypass_review_gates
    ):
        await _finish_sales_supporting_document(session, invoice)
        return

    from app.services.classification.document_type_playbook_profile_service import allows_posting_pipeline
    from app.services.invoice.non_posting_document_service import finish_non_posting_document

    if dt_definition is not None and not allows_posting_pipeline(dt_definition):
        await finish_non_posting_document(
            session,
            invoice,
            definition=dt_definition,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
            },
        )
        await _safe_auto_learn(session, invoice)
        return

    post_validate = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await _vendor_hold_unless_skipped(session, post_validate):
        invoice.status = InvoiceStatus.EXCEPTION
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.MAPPING
    await session.flush()
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice.id)
        .options(selectinload(Invoice.line_items))
    )
    loaded = (await session.execute(stmt)).scalar_one()
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.sales.sales_match_service import load_sales_order_for_invoice

    linked_po = await load_purchase_order_for_invoice(session, loaded)
    linked_so = await load_sales_order_for_invoice(session, loaded)
    map_config = await load_config_for_tenant(session, loaded.tenant_id)
    mapping, mapping_detail = _resolve_header_mapping(
        loaded,
        config=map_config,
        purchase_order=linked_po,
        sales_order=linked_so,
    )
    from app.services.purchase.team_expense_kind_service import (
        resolve_team_expense_header_mapping,
    )

    mapping, mapping_detail = await resolve_team_expense_header_mapping(
        session,
        loaded,
        map_config,
        mapping=mapping,
        detail=mapping_detail,
    )
    invoice.account_code = mapping.account_code
    invoice.account_name = mapping.account_name
    await _sync_counterparty_and_evaluate(
        session,
        loaded,
        parsed=parsed,
        config=config,
        org=org,
    )
    await sync_invoice_blob_path(session, loaded, parsed_vendor=resolved_vendor)
    invoice.raw_file_path = loaded.raw_file_path
    invoice.route_target = loaded.route_target
    if await _vendor_hold_unless_skipped(session, loaded):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = loaded.evaluation_status
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    await log_event(
        session,
        "mapping_applied",
        invoice_id=invoice.id,
        detail={
            "account_code": mapping.account_code,
            "account_name": mapping.account_name,
            "rule_type": mapping_detail.rule_type,
            "match_reason": mapping_detail.match_reason,
        },
    )

    if not should_skip(invoice, "line_gl_mapping"):
        from app.services.classification.line_gl_mapping_service import apply_line_gl_mapping

        await apply_line_gl_mapping(session, loaded, map_config)
    else:
        await _log_processing_override_skip(session, invoice, "line_gl_mapping")

    if await _hold_for_missing_line_sub_ledgers(
        session,
        invoice,
        loaded,
        map_config,
        bypass_review_gates=bypass_review_gates,
    ):
        return

    if requires_gl_mapping_review(
        loaded,
        mapping_detail,
        document_types=list(config.document_types),
    ) and not bypass_review_gates and not should_skip(invoice, "mapping_review"):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
        await log_event(
            session,
            "mapping_review_required",
            invoice_id=invoice.id,
            detail={
                "document_type_code": loaded.document_type_code,
                "route_target": invoice.route_target,
                "account_name": mapping.account_name,
                "rule_type": mapping_detail.rule_type,
                "match_reason": mapping_detail.match_reason,
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    elif requires_gl_mapping_review(
        loaded,
        mapping_detail,
        document_types=list(config.document_types),
    ) and should_skip(invoice, "mapping_review"):
        await _log_processing_override_skip(session, invoice, "mapping_review")

    await _mark_deterministic_mapping_auto_coded(
        session,
        invoice,
        loaded,
        mapping_detail,
    )

    from app.services.rule_book.rule_book_mapper import ROUTE_EXPENSES

    if (invoice.route_target or "").strip() == ROUTE_EXPENSES and is_staff_claim_sender(
        invoice.email_sender,
        config.employee_masters,
    ):
        await log_event(
            session,
            "staff_claim_guard_triggered",
            invoice_id=invoice.id,
            detail={
                "channel": infer_capture_channel(invoice.email_sender),
                **audit_document_detail(invoice),
                "reason": "mobile channel — bypassed expense rules",
            },
        )

    if await apply_team_expense_approval_gate(session, invoice):
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    from app.services.match.match_variance_gate_service import (
        build_variance_gate_audit_detail,
        evaluate_match_variance_gate,
    )

    variance_gate = await evaluate_match_variance_gate(session, loaded, config=config)
    if variance_gate.blocked:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "three_way_match_variance_unapproved",
            invoice_id=invoice.id,
            detail=build_variance_gate_audit_detail(variance_gate),
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.JOURNALING
    await session.flush()
    if await halt_if_missing_accrual_date(session, invoice):
        return
    existing_entries = (
        await session.execute(
            select(JournalEntry).where(
                *journal_entries_for_invoice(invoice.tenant_id, invoice.id),
                JournalEntry.entry_kind == JournalEntryKind.INVOICE_ACCRUAL,
            )
        )
    ).scalars().all()
    for entry in existing_entries:
        await session.delete(entry)
    await session.flush()
    backfill_invoice_amounts_from_sources(loaded)
    invoice.subtotal = loaded.subtotal
    invoice.gst = loaded.gst
    invoice.total = loaded.total
    vendor_reg_id, customer_reg_id = await resolve_counterparty_registry_ids_for_journal(
        session, invoice
    )
    from app.services.master_data.party_coa_subledger_service import (
        resolve_invoice_control_mapping,
    )

    control_mapping = await resolve_invoice_control_mapping(
        session,
        invoice,
        config,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
    )
    from app.tenant_settings import tenant_currency
    from app.services.purchase.team_expense_advance_service import (
        resolve_claim_advance_available,
    )

    tenant = await session.get(Tenant, invoice.tenant_id)
    base_currency = tenant_currency(tenant)
    advance_available = await resolve_claim_advance_available(session, invoice, config)
    journal_lines = generate_entries(
        invoice,
        mapping,
        config=config,
        sales_order=linked_so,
        vendor_registry_id=vendor_reg_id,
        customer_registry_id=customer_reg_id,
        control_mapping=control_mapping,
        base_currency=base_currency,
        advance_available=advance_available,
    )
    if not is_balanced(journal_lines):
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "journal_unbalanced",
            invoice_id=invoice.id,
            detail={
                "subtotal": float(invoice.subtotal or 0),
                "gst": float(invoice.gst or 0),
                "total": float(invoice.total or 0),
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    unresolved_control = get_unresolved_control_accounts(invoice=invoice, config=map_config)
    if unresolved_control:
        invoice.status = InvoiceStatus.EXCEPTION
        fallback = resolve_fallback_account_mapping(map_config)
        await log_event(
            session,
            "journal_control_account_unresolved",
            invoice_id=invoice.id,
            detail={
                "unresolved": unresolved_control,
                "fallback_code": fallback.account_code,
                "fallback_name": fallback.account_name,
                "route_target": invoice.route_target,
            },
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return
    try:
        await persist_journal_lines(
            session, invoice, journal_lines, base_currency=base_currency
        )
    except PeriodClosedError as exc:
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            session,
            "journal_period_closed",
            invoice_id=invoice.id,
            detail={"reason": str(exc), "route_target": invoice.route_target},
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    invoice.status = InvoiceStatus.RECONCILING
    await session.flush()
    recon_date = effective_invoice_recon_date(invoice)
    if recon_date is None:
        await halt_if_missing_accrual_date(session, invoice)
        return
    recon = await reconcile_daily(
        session,
        recon_date,
        tenant_id=invoice.tenant_id,
        current_invoice=invoice,
        config=config,
    )
    await save_reconciliation(session, recon, tenant_id=invoice.tenant_id)
    if recon.halted:
        route = (invoice.route_target or "").strip()
        non_blocking_recon = route in (ROUTE_TEAM, ROUTE_EXPENSES) or bypass_review_gates
        if non_blocking_recon:
            await log_event(
                session,
                "reconciliation_skipped",
                invoice_id=invoice.id,
                detail={"reason": recon.halt_reason, "route_target": route},
            )
        else:
            invoice.status = InvoiceStatus.EXCEPTION
            await log_event(
                session,
                "reconciliation_halted",
                invoice_id=invoice.id,
                detail={"reason": recon.halt_reason},
            )
            await _purge_accruals_after_incomplete_halt(
                session, invoice, reason="reconciliation_halted"
            )
            send_notification(invoice, InvoiceStatus.EXCEPTION)
            return

    pre_post = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    if await _vendor_hold_unless_skipped(session, pre_post):
        invoice.status = InvoiceStatus.EXCEPTION
        invoice.evaluation_status = pre_post.evaluation_status
        await _purge_accruals_after_incomplete_halt(
            session, invoice, reason="vendor_registration_hold"
        )
        send_notification(invoice, InvoiceStatus.EXCEPTION)
        return

    # Capture before _mark_invoice_processed clears processing_overrides.
    playbook_bypasses_po_hold = override_bypasses_purchase_hold(invoice)
    playbook_bypasses_so_hold = override_bypasses_sales_hold(invoice)
    _mark_invoice_processed(invoice)
    await session.flush()
    await record_team_expense_processed(session, invoice)
    from app.services.purchase.purchase_document_service import (
        is_commercial_purchase_invoice,
        sync_purchase_document,
    )

    await sync_purchase_document(session, invoice)
    if await _halt_or_bypass_purchase_awaiting_po(
        session,
        invoice,
        bypass_review_gates=bypass_review_gates,
        playbook_bypasses_po_hold=playbook_bypasses_po_hold,
    ):
        return
    if is_commercial_purchase_invoice(invoice):
        from app.services.payments.settlement_service import ensure_payment_with_audit

        await ensure_payment_with_audit(session, invoice)

    from app.services.sales.sales_document_service import (
        is_commercial_sales_invoice,
        sync_sales_document,
    )

    await sync_sales_document(session, invoice)
    if (invoice.route_target or "").strip() == ROUTE_SALES and await _halt_or_bypass_sales_awaiting_so(
        session,
        invoice,
        bypass_review_gates=bypass_review_gates,
        playbook_bypasses_so_hold=playbook_bypasses_so_hold,
    ):
        return
    if is_commercial_sales_invoice(invoice):
        from app.services.payments.settlement_service import ensure_receivable_with_audit

        await ensure_receivable_with_audit(session, invoice)
    await _safe_auto_learn(session, invoice)
    if await _stop_if_not_processed_for_publish(session, invoice):
        return
    await log_event(
        session,
        "invoice_processed",
        invoice_id=invoice.id,
        detail={
            "route_target": invoice.route_target,
            "status": invoice.status.value,
            "vendor": invoice.vendor,
            "amount": float(invoice.total) if invoice.total is not None else None,
        },
    )
    from app.services.integration.publish_service import publish_invoice_to_ledger

    await publish_invoice_to_ledger(
        session,
        invoice,
        auto=True,
        skip_if_insufficient_credits=True,
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)
