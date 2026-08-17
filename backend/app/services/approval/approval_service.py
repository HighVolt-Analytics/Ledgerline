"""Approve / reject workflows for the approval queue."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.document_type import DocumentTypeDefinition
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import (
    delete_stored_file,
    is_rejected_storage_path,
    relocate_invoice_to_rejected,
    relocate_rejected_to_vault,
    repair_invoice_stored_path,
    resolve_readable_stored,
    stored_file_available,
)
from app.services.approval.approval_pipeline_service import (
    apply_human_approval_processing_defaults,
    payable_fields_complete,
)
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL, load_config_for_tenant
from app.services.invoice.invoice_reset import (
    clear_invoice_posting_artifacts,
    reset_invoice_for_approval,
)
from app.services.approval.match_register_cleanup import cleanup_match_registers_for_invoice
from app.services.purchase.team_expense_approval import assert_team_expense_approvable
from app.services.vault.vault_invoice_paths import vault_document_type_titles_for_invoice
from app.services.vault.vault_paths import filename_from_stored

_QUEUE_STATUSES = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)

_REJECTABLE = frozenset({InvoiceStatus.EXCEPTION, InvoiceStatus.PROCESSED})

_APPROVABLE = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)

APPROVABLE_STATUSES = _APPROVABLE

_DELETABLE = frozenset(
    {InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}
)


def resolution_for_review_action(
    *,
    action: str,
    previous_status: str,
) -> str:
    """Map approve/reject/delete to Layer 7 feedback labels (stored in audit detail)."""
    action_key = (action or "").strip().lower()
    if action_key == "approve":
        return "not_duplicate"
    if action_key == "reject":
        return "confirmed_duplicate"
    if action_key in {"delete", "permanently_delete"}:
        if previous_status == InvoiceStatus.DUPLICATE_SKIPPED.value:
            return "confirmed_duplicate"
        return "merged"
    return "not_duplicate"


async def _tenant_storage_context(session: AsyncSession, inv: Invoice) -> tuple[str, str | None]:
    org = await session.get(Tenant, inv.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None
    return tenant_slug, tenant_name

_REQUESTABLE = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)


def is_queue_status(status: InvoiceStatus) -> bool:
    return status in _QUEUE_STATUSES


async def reject_invoice(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Mark invoice rejected and move stored file to rejected/{org}/{vendor}/{year}/{month}/."""
    from app.utils.logger import get_logger

    logger = get_logger(__name__)

    if inv.status == InvoiceStatus.REJECTED:
        return
    if inv.status not in _REJECTABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' cannot be rejected")

    org = await session.get(Tenant, inv.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None
    previous_status = inv.status.value
    old_path = inv.raw_file_path

    # File may already sit under rejected/ after a prior partial reject (blob moved,
    # DB rolled back). Skip Azure round-trips so we don't hold the DB session idle.
    if not is_rejected_storage_path(inv.raw_file_path):
        try:
            config = await load_config_for_tenant(session, inv.tenant_id)
            short_title, title = vault_document_type_titles_for_invoice(
                inv, list(config.document_types)
            )

            await repair_invoice_stored_path(session, inv)
            resolved = (
                await asyncio.to_thread(
                    resolve_readable_stored,
                    inv.raw_file_path,
                    tenant_id=inv.tenant_id,
                    tenant_slug=tenant_slug,
                    tenant_name=tenant_name,
                )
                if inv.raw_file_path
                else None
            )
            if resolved:
                inv.raw_file_path = resolved

            if inv.raw_file_path and await asyncio.to_thread(
                stored_file_available,
                inv.raw_file_path,
                tenant_id=inv.tenant_id,
                tenant_slug=tenant_slug,
                tenant_name=tenant_name,
            ):
                filename = filename_from_stored(inv.raw_file_path)
                new_path = await asyncio.to_thread(
                    relocate_invoice_to_rejected,
                    inv.raw_file_path,
                    inv.tenant_id,
                    tenant_slug,
                    inv.id,
                    filename,
                    tenant_name=tenant_name,
                    vendor_name=inv.vendor,
                    storage_vendor_slug=inv.storage_vendor_slug,
                    invoice_no=inv.invoice_no,
                    invoice_date=inv.invoice_date,
                    route_target=inv.route_target,
                    document_type_code=inv.document_type_code,
                    document_type_short_title=short_title,
                    document_type_title=title,
                )
                if new_path != inv.raw_file_path:
                    inv.raw_file_path = new_path
        except Exception as exc:
            # Status must still flip to rejected; blob can be repaired later.
            logger.warning(
                "reject_blob_relocate_failed",
                invoice_id=inv.id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    if inv.status == InvoiceStatus.PROCESSED:
        await clear_invoice_posting_artifacts(session, inv)

    inv.status = InvoiceStatus.REJECTED
    await session.flush()
    await log_event(
        session,
        "invoice_rejected",
        invoice_id=inv.id,
        detail={
            "previous_status": previous_status,
            "old_path": old_path,
            "new_path": inv.raw_file_path,
            "resolution": resolution_for_review_action(
                action="reject",
                previous_status=previous_status,
            ),
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def restore_rejected_invoice_file_if_needed(
    session: AsyncSession,
    inv: Invoice,
) -> None:
    """Move a rejected blob back to invoice/ vault before reprocessing."""
    if inv.status != InvoiceStatus.REJECTED or not inv.raw_file_path:
        return

    org = await session.get(Tenant, inv.tenant_id)
    tenant_slug = org.slug if org else "default"
    tenant_name = org.name if org else None
    config = await load_config_for_tenant(session, inv.tenant_id)
    short_title, title = vault_document_type_titles_for_invoice(inv, list(config.document_types))
    filename = filename_from_stored(inv.raw_file_path)
    inv.raw_file_path = relocate_rejected_to_vault(
        inv.raw_file_path,
        inv.tenant_id,
        tenant_slug,
        inv.storage_vendor_slug or "unknown",
        inv.id,
        inv.file_hash or "",
        filename,
        tenant_name=tenant_name,
        vendor_name=inv.vendor,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        route_target=inv.route_target,
        document_type_code=inv.document_type_code,
        document_type_short_title=short_title,
        document_type_title=title,
    )


def _assert_invoice_ready_for_approval(
    inv: Invoice,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> None:
    from app.services.classification.document_type_field_checks import field_is_present
    from app.services.classification.document_type_playbook_service import (
        approval_enforced_required_fields,
    )
    from app.services.classification.document_type_rule_engine import build_document_classifier_context
    from app.services.invoice.invoice_data import invoice_data_from_invoice

    compulsory = approval_enforced_required_fields(definition)
    if compulsory:
        parsed = invoice_data_from_invoice(inv)
        ctx = build_document_classifier_context(invoice=inv, parsed=parsed)
        missing = [
            key
            for key in compulsory
            if not field_is_present(key, invoice=inv, parsed=parsed, ctx=ctx)
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                f"Cannot approve: missing compulsory field(s): {joined}. "
                "Save corrections before approving."
            )


async def approve_invoice_for_reprocess(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Re-queue invoice for pipeline; preserve user-corrected extracted fields."""
    if inv.status not in _APPROVABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' is not in the approval queue")

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await assert_team_expense_approvable(session, loaded)
    from app.services.classification.document_type_catalog import get_document_type_definition

    config = await load_config_for_tenant(session, loaded.tenant_id)
    definition = get_document_type_definition(
        loaded.document_type_code,
        document_types=config.document_types,
    )
    _assert_invoice_ready_for_approval(loaded, definition=definition)
    if payable_fields_complete(loaded, definition):
        apply_human_approval_processing_defaults(loaded)
    previous_status = inv.status.value
    await repair_invoice_stored_path(session, inv)

    await restore_rejected_invoice_file_if_needed(session, inv)

    if not stored_file_available(inv.raw_file_path, tenant_id=inv.tenant_id):
        raise ValueError("Invoice has no stored file to process")

    await reset_invoice_for_approval(session, inv)
    await log_event(
        session,
        "invoice_approved",
        invoice_id=inv.id,
        detail={
            "previous_status": previous_status,
            "resolution": resolution_for_review_action(
                action="approve",
                previous_status=previous_status,
            ),
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def confirm_invoice_for_process(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Re-queue for pipeline without recording manager approval.

    Field edits are preserved. Document-type / team-expense approval gates
    still hold when policy requires a separate approver.
    """
    if inv.status != InvoiceStatus.EXCEPTION:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot confirm and process"
        )

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    await assert_team_expense_approvable(session, loaded)
    from app.services.classification.document_type_catalog import get_document_type_definition

    config = await load_config_for_tenant(session, loaded.tenant_id)
    definition = get_document_type_definition(
        loaded.document_type_code,
        document_types=config.document_types,
    )
    _assert_invoice_ready_for_approval(loaded, definition=definition)
    previous_status = inv.status.value
    await repair_invoice_stored_path(session, inv)
    await restore_rejected_invoice_file_if_needed(session, inv)

    if not stored_file_available(inv.raw_file_path, tenant_id=inv.tenant_id):
        raise ValueError("Invoice has no stored file to process")

    inv.approval_chain = None
    loaded.approval_chain = None
    await reset_invoice_for_approval(session, inv)
    await log_event(
        session,
        "invoice_confirm_processed",
        invoice_id=inv.id,
        detail={
            "previous_status": previous_status,
            "manager_approval": False,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def request_approval(
    session: AsyncSession,
    inv: Invoice,
    *,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> None:
    """Route an invoice to the human approval queue."""
    if inv.status == InvoiceStatus.PROCESSED:
        raise ValueError(
            "This document is already posted. Reject it first if you need "
            "to return it to the approval queue."
        )
    if inv.status in _QUEUE_STATUSES:
        raise ValueError("Invoice is already in the approval queue")
    if inv.status not in _REQUESTABLE:
        raise ValueError(f"Invoice status '{inv.status.value}' cannot request approval")

    previous_status = inv.status.value
    inv.status = InvoiceStatus.EXCEPTION
    inv.evaluation_status = EVAL_PENDING_APPROVAL
    await session.flush()
    await log_event(
        session,
        "approval_requested",
        invoice_id=inv.id,
        detail={"previous_status": previous_status},
        actor_name=actor_name,
        actor_email=actor_email,
    )


async def permanently_delete_invoice(session: AsyncSession, inv: Invoice) -> None:
    """Permanently remove a rejected/duplicate invoice and its stored file."""
    tenant_slug, tenant_name = await _tenant_storage_context(session, inv)
    await repair_invoice_stored_path(session, inv)
    deletable = inv.status in _DELETABLE
    if not deletable and inv.status == InvoiceStatus.PROCESSED:
        deletable = is_rejected_storage_path(inv.raw_file_path)
    if not deletable:
        raise ValueError(
            f"Invoice status '{inv.status.value}' cannot be permanently deleted. "
            "Reject the document first, then delete it from the Rejected column."
        )

    previous_status = inv.status.value
    stored_path = inv.raw_file_path
    prefer_rejected = inv.status in _DELETABLE or is_rejected_storage_path(stored_path)
    await log_event(
        session,
        "invoice_permanently_deleted",
        invoice_id=inv.id,
        detail={
            "status": previous_status,
            "vendor": inv.vendor,
            "invoice_no": inv.invoice_no,
            "stored_path": stored_path,
            "resolution": resolution_for_review_action(
                action="delete",
                previous_status=previous_status,
            ),
        },
    )
    delete_stored_file(
        stored_path,
        tenant_id=inv.tenant_id,
        tenant_slug=tenant_slug,
        tenant_name=tenant_name,
        invoice_id=inv.id,
        prefer_rejected=prefer_rejected,
    )
    await cleanup_match_registers_for_invoice(session, inv.id)
    await session.delete(inv)
    await session.flush()
