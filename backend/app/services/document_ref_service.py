"""Org-scoped stable document references (DOC-1, DOC-2, …)."""

from __future__ import annotations

import re

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice

_DOC_REF = re.compile(r"^(?:DT|DOC)-(\d+)$", re.I)
# Namespace for pg_advisory_xact_lock(key1, key2) — avoids collisions with other locks.
_DOC_REF_LOCK_NAMESPACE = 8_700_421


def format_document_ref(sequence: int) -> str:
    return f"DOC-{sequence}"


def display_document_ref(invoice: Invoice) -> str:
    ref = (getattr(invoice, "document_ref", None) or "").strip()
    if ref:
        return ref
    return "—"


def invoice_log_fields(invoice: Invoice | None) -> dict[str, int | str]:
    """Structured log / audit fields: always include document_ref when assigned."""
    if invoice is None:
        return {}
    fields: dict[str, int | str] = {"invoice_id": invoice.id}
    ref = (invoice.document_ref or "").strip()
    if ref:
        fields["document_ref"] = ref
    return fields


def audit_document_detail(invoice: Invoice | None, **extra: object) -> dict[str, object]:
    """Audit event detail with stable document_ref (not DB id as display id)."""
    detail: dict[str, object] = dict(extra)
    if invoice is not None:
        ref = (invoice.document_ref or "").strip()
        if ref:
            detail["document_ref"] = ref
        detail["document_id"] = ref or None
    return detail


def _session_supports_advisory_lock(session: AsyncSession) -> bool:
    try:
        bind = session.get_bind()
    except Exception:
        return False
    return bind is not None and bind.dialect.name == "postgresql"


async def _acquire_document_ref_lock(session: AsyncSession, org_id: int) -> None:
    """Serialize DOC-n allocation per org (bulk upload runs concurrent requests)."""
    if not _session_supports_advisory_lock(session):
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :org_id)"),
        {"namespace": _DOC_REF_LOCK_NAMESPACE, "org_id": org_id},
    )


async def next_document_ref(session: AsyncSession, org_id: int) -> str:
    rows = await session.execute(
        select(Invoice.document_ref).where(Invoice.org_id == org_id)
    )
    max_seq = 0
    for (ref,) in rows.all():
        if not ref:
            continue
        match = _DOC_REF.match(str(ref).strip())
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return format_document_ref(max_seq + 1)


async def allocate_next_document_ref(session: AsyncSession, org_id: int) -> str:
    """Reserve the next org document ref under an advisory lock."""
    await _acquire_document_ref_lock(session, org_id)
    return await next_document_ref(session, org_id)


async def assign_document_ref(session: AsyncSession, invoice: Invoice) -> str:
    existing = (invoice.document_ref or "").strip()
    if existing:
        return existing
    ref = await allocate_next_document_ref(session, invoice.org_id)
    invoice.document_ref = ref
    return ref
