"""Re-apply document type classification from stored invoice fields (policy scorer)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.classification_learning_service import human_confirmed_document_type
from app.services.finance_dt_policy_scorer import score_all_enabled_dts
from app.services.invoice_data import invoice_data_from_invoice
from app.services.invoice_evaluation_service import apply_invoice_evaluation, load_config_for_tenant
from app.services.llm_document_service import apply_document_type_to_invoice

_SKIP_RECLASSIFY = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


def _has_parse_snapshot(invoice: Invoice) -> bool:
    return bool(
        (invoice.vendor or "").strip()
        or (invoice.invoice_no or "").strip()
        or invoice.total is not None
        or (invoice.document_text or "").strip()
    )


def _enabled_document_type_codes(config: RuleBookConfigPayload) -> set[str]:
    return {
        (dt.code or "").strip().upper()
        for dt in config.document_types
        if dt.enabled and (dt.code or "").strip()
    }


async def should_reclassify_invoice_document_type(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload,
    force: bool = False,
) -> bool:
    """Whether policy scoring may change document_type_code on this invoice."""
    if force:
        return True
    if invoice.status in _SKIP_RECLASSIFY or not _has_parse_snapshot(invoice):
        return False
    if await human_confirmed_document_type(session, invoice_id=invoice.id):
        return False
    stored = (invoice.document_type_code or "").strip().upper()
    if not stored:
        return True
    return stored not in _enabled_document_type_codes(config)


async def reclassify_invoice_document_type(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
    parse_confidence: object | None = None,
    force: bool = False,
) -> bool:
    """Re-run DT policy scoring from persisted fields. Returns True if code/confidence changed."""
    del parse_confidence  # legacy parameter; LLM-first path uses full pipeline reprocess
    if config is None:
        config = await load_config_for_tenant(session, invoice.tenant_id)

    if not await should_reclassify_invoice_document_type(
        session,
        invoice,
        config=config,
        force=force,
    ):
        return False

    parsed = invoice_data_from_invoice(invoice)
    before = (
        (invoice.document_type_code or "").strip().upper(),
        float(invoice.document_type_confidence or 0.0),
    )
    policy = score_all_enabled_dts(
        invoice=invoice,
        parsed=parsed,
        document_types=config.document_types,
    )
    if not policy.winner_dt:
        return False

    apply_document_type_to_invoice(
        invoice,
        code=policy.winner_dt,
        confidence=policy.winner_confidence,
    )
    after = (
        (invoice.document_type_code or "").strip().upper(),
        float(invoice.document_type_confidence or 0.0),
    )
    if before != after:
        await apply_invoice_evaluation(session, invoice, config=config, enqueue_pending=False)
        await session.flush()
        return True
    return False


async def reclassify_invoices_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: int,
    invoices: Sequence[Invoice],
    config: RuleBookConfigPayload | None = None,
    force: bool = False,
) -> list[int]:
    changed: list[int] = []
    if config is None:
        tid = invoices[0].tenant_id if invoices else tenant_id
        config = await load_config_for_tenant(session, tid)
    for invoice in invoices:
        if await reclassify_invoice_document_type(
            session,
            invoice,
            config=config,
            force=force,
        ):
            changed.append(invoice.id)
    return changed
