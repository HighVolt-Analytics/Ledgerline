"""Audit log helpers for dossier read paths."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

# Events referenced by dossier pipeline, summary, and approval builders.
DOSSIER_AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "email_ingested",
        "invoice_uploaded",
        "invoice_file_attached",
        "duplicate_skipped",
        "duplicate_in_progress",
        "duplicate_reingest_rejected",
        "parse_completed",
        "invoice_parsed",
        "parsing_failed",
        "document_classified",
        "playbook_evaluated",
        "vendor_registration_hold",
        "validation_passed",
        "validation_failed",
        "routing_review_required",
        "three_way_match_evaluated",
        "purchase_variance_approved",
        "invoice_approved",
        "approval_required",
        "approval_requested",
        "team_expense_approval_required",
        "mapping_applied",
        "mapping_review_required",
        "reconciliation_halted",
        "reconciliation_skipped",
        "invoice_processed",
        "purchase_document_processed",
        "invoice_published_to_ledger",
        "vault_stored",
    }
)


async def fetch_dossier_audit_logs(
    session: AsyncSession,
    invoice_id: int,
) -> list[AuditLog]:
    """Load only audit events needed to render dossier pipeline + approval."""
    return list(
        (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == invoice_id,
                    AuditLog.event.in_(DOSSIER_AUDIT_EVENTS),
                )
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    )


async def fetch_dossier_audit_logs_for_invoices(
    session: AsyncSession,
    invoice_ids: list[int],
) -> dict[int, list[AuditLog]]:
    if not invoice_ids:
        return {}
    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event.in_(DOSSIER_AUDIT_EVENTS),
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    grouped: dict[int, list[AuditLog]] = {i: [] for i in invoice_ids}
    for row in rows:
        if row.invoice_id is not None:
            grouped.setdefault(row.invoice_id, []).append(row)
    return grouped
