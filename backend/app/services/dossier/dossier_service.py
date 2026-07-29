"""Assemble dossier hero view from invoice + related services."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.payment import Payment, PaymentStatus
from app.schemas.dossier import (
    DossierLinkedDocumentResponse,
    DossierLinkedDocumentsResponse,
    DossierPipelineStepResponse,
    DossierSummaryResponse,
)
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.sales.counterparty_service import (
    counterparty_side_for_route,
    resolve_counterparty_from_invoice_context,
)
from app.services.dossier.document_ref_service import display_document_ref, dossier_public_id, parse_dossier_id_token
from app.services.classification.document_type_catalog import ROUTE_SALES
from app.services.purchase.po_reference import (
    effective_po_reference,
    invoice_po_reference_equals,
    is_plausible_po_reference,
    normalize_po_link_token,
)
from app.services.sales.so_reference import (
    invoice_so_reference_equals,
    is_plausible_so_reference,
    normalize_so_link_token,
    resolve_so_reference_from_invoice,
)
from app.services.classification.document_type_playbook_service import resolve_definition_for_invoice
from app.services.dossier.dossier_approval_service import build_dossier_approval_chain
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier.dossier_match_service import enrich_match_pipeline_step
from app.services.dossier.dossier_pipeline_service import (
    _is_vision_understood_hold,
    build_dossier_pipeline,
    build_understood_dossier_pipeline,
    classification_review_pending,
    first_pipeline_bottleneck,
    first_pipeline_failure,
)
from app.services.shared.file_storage import has_stored_path
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.reports.matrix_service import derive_matrix_payment_status
from app.services.invoice.pipeline_stages import (
    _actor_name,
    _latest_log,
    _source_label,
    resolve_pipeline_active_path,
    vision_posting_continues,
)
from app.services.integration.publish_service import is_published_from_audit_logs
from app.tenant_settings import tenant_today


def dossier_capture_channel(invoice: Invoice) -> str:
    src = (invoice.capture_source or "").strip().lower()
    if src == "email":
        return "Email capture"
    if src == "whatsapp":
        return "WhatsApp capture"
    if src == "edi":
        return "EDI capture"
    if invoice.connected_mailbox_id or invoice.email_sender:
        return "Email capture"
    return "Upload"


def _money(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _confidence_pct(value: float | None, *, floor: bool = False) -> int:
    if value is None:
        return 0
    if value <= 1:
        pct = value * 100
        return int(pct) if floor else int(round(pct))
    return int(value) if floor else int(round(value))


def _document_type_title(code: str, document_types) -> str:
    token = (code or "").strip().upper()
    for row in document_types:
        if row.code.upper() == token:
            return row.title or row.short_title or token
    return token or "Document"


def _vision_document_type_label(invoice: Invoice) -> str:
    """AI / printed document name from vision header (no catalogue code required)."""
    from app.services.dossier.vision_bundle_linkage import vision_document_type_label

    return vision_document_type_label(invoice)


def _owner_from_logs(logs: list[AuditLog]) -> str:
    for event in ("invoice_approved", "invoice_published_to_ledger", "approval_requested"):
        log = _latest_log(logs, event)
        if log:
            actor = _actor_name(log.detail if isinstance(log.detail, dict) else None)
            if actor:
                return actor
    return "System"


def _resolve_dossier_pipeline_path(
    invoice: Invoice,
    logs: list[AuditLog],
) -> Literal["understood", "not_understood", "unknown"]:
    """Prefer audit path; fall back to vision hold so UI can prune to 7 stages."""
    path = resolve_pipeline_active_path(logs)
    if path != "unknown":
        return path
    if _is_vision_understood_hold(invoice, logs):
        return "understood"
    return "unknown"


def _sla(
    invoice: Invoice,
    *,
    today: date,
    logs: list[AuditLog] | None = None,
) -> tuple[str, bool]:
    from app.services.invoice.pipeline_stages import vision_posting_continues

    if invoice.status == InvoiceStatus.PROCESSED:
        return "Posted", False
    if invoice.status == InvoiceStatus.EXCEPTION:
        if (
            logs
            and _resolve_dossier_pipeline_path(invoice, logs) == "understood"
            and not vision_posting_continues(logs)
        ):
            return "Vaulted", False
        return "Blocked", True
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Blocked", False
    if invoice.due_date and invoice.due_date < today:
        return "Overdue", True
    return "In progress", False


def _payment_status_key(invoice: Invoice, payment: Payment | None) -> tuple[str | None, str | None]:
    label = derive_matrix_payment_status(invoice, payment)
    if payment is None:
        return None, None
    if payment.status == PaymentStatus.PAID:
        return "paid", label
    if payment.status == PaymentStatus.FAILED:
        return "failed", label
    if payment.status in (PaymentStatus.AWAITING, PaymentStatus.QUEUE, PaymentStatus.SCHEDULED):
        return "awaiting", label
    return None, label


def _blocker_detail_from_step(step: DossierPipelineStepResponse | None) -> str | None:
    if step is None:
        return None
    if step.failure_reason and step.failure_reason.strip():
        return step.failure_reason.strip()
    detail = (step.detail or "").strip()
    if detail and detail != "—":
        return detail
    return None


def _derive_outcome(
    invoice: Invoice,
    logs: list[AuditLog],
    pipeline_fail: bool,
    *,
    published: bool,
    payment: Payment | None,
    fail_detail: str | None,
) -> tuple[str, str]:
    from app.services.invoice.pipeline_stages import vision_posting_continues

    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "blocked", fail_detail or "Duplicate file skipped"
    if invoice.status == InvoiceStatus.REJECTED:
        return "blocked", "Invoice rejected"
    # Vault-only Understood path intentionally holds as EXCEPTION after bundle + vault — not a failure.
    if (
        invoice.status == InvoiceStatus.EXCEPTION
        and not pipeline_fail
        and _resolve_dossier_pipeline_path(invoice, logs) == "understood"
        and not vision_posting_continues(logs)
    ):
        return "vaulted", "Understood path — bundled and stored in vault"
    if pipeline_fail or invoice.status == InvoiceStatus.EXCEPTION:
        return "blocked", fail_detail or "Pipeline blocked — review required"
    if payment and payment.status == PaymentStatus.FAILED:
        return "parked", "Payment failed — parked for review"
    if payment and payment.status in (PaymentStatus.AWAITING, PaymentStatus.QUEUE) and invoice.status == InvoiceStatus.PROCESSED:
        return "parked", "Posted — awaiting payment release"
    if (invoice.route_target or "").strip().lower() == "vault":
        if any(log.event == "vault_stored" for log in logs) or invoice.status == InvoiceStatus.PROCESSED:
            return "in_progress", "Stored in document vault"
    doc_type = (invoice.purchase_document_type or "").strip().lower()
    if doc_type in ("po", "grn") and invoice.status == InvoiceStatus.PROCESSED:
        return "auto_posted", "Purchase document processed"
    if invoice.status == InvoiceStatus.PROCESSED:
        approved = any(log.event == "invoice_approved" for log in logs)
        if published:
            return ("manual_posted" if approved else "auto_posted"), "Posted to ledger"
        return "in_progress", "Processed — ready to post"
    return "in_progress", "Processing"


def _linked_doc_dt_label(code: str, document_types) -> str:
    token = (code or "").strip().upper()
    for row in document_types:
        if row.code.upper() == token:
            return row.title or row.short_title or token
    return token or "Document"


@dataclass
class LinkageSiblingCache:
    """Prefetched tenant invoices keyed by linkage fields (bundle export batching)."""

    by_invoice_no: dict[str, list[Invoice]] = field(default_factory=dict)
    by_po_reference: dict[str, list[Invoice]] = field(default_factory=dict)
    by_so_reference: dict[str, list[Invoice]] = field(default_factory=dict)


def _index_linkage_sibling(
    bucket: dict[str, list[Invoice]],
    key: str | None,
    row: Invoice,
) -> None:
    token = (key or "").strip()
    if not token:
        return
    bucket.setdefault(token, []).append(row)


async def build_linkage_sibling_cache(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchors: list[Invoice],
) -> LinkageSiblingCache:
    """Load invoices that may link to anchors via invoice_no or PO/SO.

    One-hop harvest: after loading invoice_no matches, also pull docs that share
    PO/SO values found on those siblings (so packing-list PO can pull a GRN).
    """
    from sqlalchemy import func, or_

    from app.services.extraction.invoice_no_sanitizer import invoice_no_link_tokens

    invoice_nos: set[str] = set()
    po_refs: set[str] = set()
    so_refs: set[str] = set()

    for anchor in anchors:
        invoice_nos.update(invoice_no_link_tokens(anchor))
        primary = (anchor.invoice_no or "").strip()
        if primary:
            invoice_nos.add(primary)
        po_ref = effective_po_reference(anchor.po_reference)
        if po_ref and is_plausible_po_reference(po_ref):
            po_refs.add(normalize_po_link_token(po_ref))
        so_ref = resolve_so_reference_from_invoice(anchor)
        if so_ref and is_plausible_so_reference(so_ref):
            so_refs.add(normalize_so_link_token(so_ref))

    if not invoice_nos and not po_refs and not so_refs:
        return LinkageSiblingCache()

    async def _load(invoice_nos_: set[str], po_refs_: set[str], so_refs_: set[str]) -> list[Invoice]:
        clauses = []
        if invoice_nos_:
            token_list = list(invoice_nos_)
            upper_invoice_nos = [t.upper() for t in token_list]
            clauses.append(
                or_(
                    func.upper(func.coalesce(Invoice.invoice_no, "")).in_(upper_invoice_nos),
                    Invoice.invoice_no.in_(token_list),
                )
            )
        if po_refs_:
            clauses.append(
                func.upper(func.coalesce(Invoice.po_reference, "")).in_(list(po_refs_))
            )
        if so_refs_:
            clauses.append(
                func.upper(func.coalesce(Invoice.so_reference, "")).in_(list(so_refs_))
            )
        if not clauses:
            return []
        return list(
            (
                await session.execute(
                    select(Invoice)
                    .where(Invoice.tenant_id == tenant_id, or_(*clauses))
                    .order_by(Invoice.id.asc())
                )
            )
            .scalars()
            .all()
        )

    rows = await _load(invoice_nos, po_refs, so_refs)
    by_id = {row.id: row for row in rows}

    # One-hop: harvest PO/SO from invoice_no-linked rows, then load those refs.
    harvested_po = set(po_refs)
    harvested_so = set(so_refs)
    for row in rows:
        po_ref = effective_po_reference(row.po_reference)
        if po_ref and is_plausible_po_reference(po_ref):
            harvested_po.add(normalize_po_link_token(po_ref))
        so_ref = resolve_so_reference_from_invoice(row)
        if so_ref and is_plausible_so_reference(so_ref):
            harvested_so.add(normalize_so_link_token(so_ref))

    new_po = harvested_po - po_refs
    new_so = harvested_so - so_refs
    if new_po or new_so:
        for row in await _load(set(), new_po, new_so):
            by_id[row.id] = row

    cache = LinkageSiblingCache()
    for row in by_id.values():
        for token in invoice_no_link_tokens(row):
            _index_linkage_sibling(cache.by_invoice_no, token, row)
        primary = (row.invoice_no or "").strip()
        if primary:
            _index_linkage_sibling(cache.by_invoice_no, primary, row)
        # Index PO/SO under case-folded keys so lookups match playbook equality.
        _index_linkage_sibling(
            cache.by_po_reference, normalize_po_link_token(row.po_reference) or None, row
        )
        _index_linkage_sibling(
            cache.by_so_reference, normalize_so_link_token(row.so_reference) or None, row
        )
    return cache


async def fetch_linked_invoices_by_invoice_no(
    session: AsyncSession,
    anchor: Invoice,
    *,
    linkage_cache: LinkageSiblingCache | None = None,
) -> list[Invoice]:
    """Sibling invoices sharing any invoice_no token (primary or secondary) with the anchor."""
    from sqlalchemy import func, or_

    from app.services.extraction.invoice_no_sanitizer import invoice_no_link_tokens

    tokens = invoice_no_link_tokens(anchor)
    if not tokens:
        return []
    if linkage_cache is not None:
        siblings: list[Invoice] = []
        seen: set[int] = set()
        for token in tokens:
            for row in linkage_cache.by_invoice_no.get(token, []):
                if row.id == anchor.id or row.id in seen:
                    continue
                if invoice_no_link_tokens(row) & tokens:
                    siblings.append(row)
                    seen.add(row.id)
            # Cache keys may be original-case primary only.
            for row in linkage_cache.by_invoice_no.get(token.lower(), []):
                if row.id == anchor.id or row.id in seen:
                    continue
                if invoice_no_link_tokens(row) & tokens:
                    siblings.append(row)
                    seen.add(row.id)
        return siblings

    token_list = list(tokens)
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == anchor.tenant_id,
                Invoice.id != anchor.id,
                or_(
                    func.upper(Invoice.invoice_no).in_(token_list),
                    Invoice.invoice_no.in_(token_list),
                ),
            )
            .order_by(Invoice.id.asc())
        )
    ).scalars().all()
    return [row for row in rows if invoice_no_link_tokens(row) & tokens]


async def fetch_linked_invoices_by_po_reference(
    session: AsyncSession,
    anchor: Invoice,
    *,
    linkage_cache: LinkageSiblingCache | None = None,
) -> list[Invoice]:
    """Sibling invoices sharing the same plausible PO reference as the anchor."""
    po_ref = effective_po_reference(anchor.po_reference)
    if not po_ref or not is_plausible_po_reference(po_ref):
        return []
    return await fetch_invoices_by_po_reference_token(
        session,
        tenant_id=anchor.tenant_id,
        po_ref=po_ref,
        exclude_id=anchor.id,
        linkage_cache=linkage_cache,
    )


async def fetch_linked_invoices_by_so_reference(
    session: AsyncSession,
    anchor: Invoice,
    *,
    linkage_cache: LinkageSiblingCache | None = None,
) -> list[Invoice]:
    """Sibling invoices sharing the same plausible SO reference as the anchor."""
    so_ref = resolve_so_reference_from_invoice(anchor)
    if not so_ref or not is_plausible_so_reference(so_ref):
        return []
    return await fetch_invoices_by_so_reference_token(
        session,
        tenant_id=anchor.tenant_id,
        so_ref=so_ref,
        exclude_id=anchor.id,
        linkage_cache=linkage_cache,
    )


async def fetch_invoices_by_po_reference_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    po_ref: str,
    exclude_id: int | None = None,
    linkage_cache: LinkageSiblingCache | None = None,
) -> list[Invoice]:
    """Tenant invoices sharing an explicit PO reference token."""
    token_src = effective_po_reference(po_ref) or (po_ref or "").strip()
    if not token_src or not is_plausible_po_reference(token_src):
        return []
    po_token = normalize_po_link_token(token_src)
    if linkage_cache is not None:
        return [
            row
            for row in linkage_cache.by_po_reference.get(po_token, [])
            if exclude_id is None or row.id != exclude_id
        ]
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                invoice_po_reference_equals(token_src),
                *([Invoice.id != exclude_id] if exclude_id is not None else []),
            )
            .order_by(Invoice.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def fetch_invoices_by_so_reference_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    so_ref: str,
    exclude_id: int | None = None,
    linkage_cache: LinkageSiblingCache | None = None,
) -> list[Invoice]:
    """Tenant invoices sharing an explicit SO reference token."""
    token_src = (so_ref or "").strip()
    if not token_src or not is_plausible_so_reference(token_src):
        return []
    so_token = normalize_so_link_token(token_src)
    if linkage_cache is not None:
        return [
            row
            for row in linkage_cache.by_so_reference.get(so_token, [])
            if exclude_id is None or row.id != exclude_id
        ]
    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                invoice_so_reference_equals(token_src),
                *([Invoice.id != exclude_id] if exclude_id is not None else []),
            )
            .order_by(Invoice.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _linked_invoice_ids(response: DossierLinkedDocumentsResponse) -> set[int]:
    ids: set[int] = set()
    for doc in response.documents:
        if doc.invoice_id is not None:
            ids.add(doc.invoice_id)
        if doc.manual_link is not None:
            ids.add(doc.manual_link.invoice_id)
    return ids


def _invoice_no_linked_document(
    row: Invoice,
    *,
    invoice_no: str,
    document_types,
) -> DossierLinkedDocumentResponse:
    code = (row.document_type_code or "").strip().upper()
    return DossierLinkedDocumentResponse(
        id=f"invoice-no-{row.id}",
        document_type_code=code,
        label=_linked_doc_dt_label(code, document_types),
        document_ref=display_document_ref(row),
        invoice_no=(row.invoice_no or invoice_no).strip() or None,
        counterparty=(row.vendor or "").strip() or None,
        present=True,
        requirement="advisory",
        linked_dossier_id=dossier_public_id(row),
        invoice_id=row.id,
        is_anchor=False,
        has_file=has_stored_path(row.raw_file_path),
        linkage_detail=f"Linked on invoice no {invoice_no}",
        link_kind="invoice_no",
    )


def _reference_linked_document(
    row: Invoice,
    *,
    reference_label: str,
    link_kind: str,
    document_types,
    linkage_detail: str | None = None,
) -> DossierLinkedDocumentResponse:
    code = (row.document_type_code or "").strip().upper()
    return DossierLinkedDocumentResponse(
        id=f"{link_kind}-{row.id}",
        document_type_code=code,
        label=_linked_doc_dt_label(code, document_types),
        document_ref=display_document_ref(row),
        invoice_no=(row.invoice_no or "").strip() or None,
        counterparty=(row.vendor or "").strip() or None,
        present=True,
        requirement="advisory",
        linked_dossier_id=dossier_public_id(row),
        invoice_id=row.id,
        is_anchor=False,
        has_file=has_stored_path(row.raw_file_path),
        linkage_detail=linkage_detail or f"Linked on {reference_label}",
        link_kind=link_kind,
    )


async def append_invoice_no_linked_documents(
    session: AsyncSession,
    anchor: Invoice,
    response: DossierLinkedDocumentsResponse,
    *,
    document_types=None,
    linkage_cache: LinkageSiblingCache | None = None,
) -> DossierLinkedDocumentsResponse:
    """
    Append invoices that share anchor.invoice_no (additive; dedupe by invoice id).

    Does not replace bundle / po_reference linked docs.
    """
    invoice_no = (anchor.invoice_no or "").strip()
    if not invoice_no:
        return response

    if document_types is None:
        document_types = (
            await load_posting_config_for_tenant(session, anchor.tenant_id)
        ).document_types

    siblings = await fetch_linked_invoices_by_invoice_no(
        session, anchor, linkage_cache=linkage_cache
    )
    if not siblings:
        return response

    seen = _linked_invoice_ids(response)
    extra: list[DossierLinkedDocumentResponse] = []
    for row in siblings:
        if row.id in seen:
            continue
        extra.append(
            _invoice_no_linked_document(
                row,
                invoice_no=invoice_no,
                document_types=document_types,
            )
        )
        seen.add(row.id)

    if not extra:
        return response

    linkage_key = response.linkage_key or invoice_no
    linkage_label = response.linkage_label
    linkage_kind = response.linkage_kind
    if response.linkage_kind in {"standalone", "shipment_ref"}:
        linkage_kind = "invoice_no"
        linkage_label = f"Invoice no · {invoice_no}"

    return response.model_copy(
        update={
            "linkage_kind": linkage_kind,
            "linkage_key": linkage_key,
            "linkage_label": linkage_label,
            "documents": list(response.documents) + extra,
        }
    )


async def append_reference_linked_documents(
    session: AsyncSession,
    anchor: Invoice,
    response: DossierLinkedDocumentsResponse,
    *,
    document_types=None,
    linkage_cache: LinkageSiblingCache | None = None,
) -> DossierLinkedDocumentsResponse:
    """
    Append invoices linked by PO or SO reference (additive; dedupe by invoice id).

    Unions with bundle / invoice_no linked docs so transactional anchors with both
    invoice no and reference no export all supporting documents.
    """
    if document_types is None:
        document_types = (
            await load_posting_config_for_tenant(session, anchor.tenant_id)
        ).document_types

    seen = _linked_invoice_ids(response)
    extra: list[DossierLinkedDocumentResponse] = []

    po_ref = effective_po_reference(anchor.po_reference)
    if po_ref and is_plausible_po_reference(po_ref):
        for row in await fetch_linked_invoices_by_po_reference(
            session, anchor, linkage_cache=linkage_cache
        ):
            if row.id in seen:
                continue
            extra.append(
                _reference_linked_document(
                    row,
                    reference_label=po_ref,
                    link_kind="po_reference",
                    document_types=document_types,
                )
            )
            seen.add(row.id)

    so_ref = resolve_so_reference_from_invoice(anchor)
    if so_ref and is_plausible_so_reference(so_ref):
        for row in await fetch_linked_invoices_by_so_reference(
            session, anchor, linkage_cache=linkage_cache
        ):
            if row.id in seen:
                continue
            extra.append(
                _reference_linked_document(
                    row,
                    reference_label=so_ref,
                    link_kind="so_reference",
                    document_types=document_types,
                )
            )
            seen.add(row.id)

    if not extra:
        return response

    return response.model_copy(
        update={"documents": list(response.documents) + extra},
    )


async def append_harvested_reference_linked_documents(
    session: AsyncSession,
    anchor: Invoice,
    response: DossierLinkedDocumentsResponse,
    *,
    document_types=None,
    linkage_cache: LinkageSiblingCache | None = None,
) -> DossierLinkedDocumentsResponse:
    """
    One-hop invoice-hub expansion: harvest PO/SO from the hub and invoice_no
    siblings, then append docs that share those references.

    When the hub has no invoice_no, falls back to anchor-only PO/SO append.
    Does not re-harvest from PO/SO-only docs (one hop only).
    """
    invoice_no = (anchor.invoice_no or "").strip()
    if not invoice_no:
        return await append_reference_linked_documents(
            session,
            anchor,
            response,
            document_types=document_types,
            linkage_cache=linkage_cache,
        )

    if document_types is None:
        document_types = (
            await load_posting_config_for_tenant(session, anchor.tenant_id)
        ).document_types

    siblings = await fetch_linked_invoices_by_invoice_no(
        session, anchor, linkage_cache=linkage_cache
    )
    sources = [anchor, *siblings]

    po_by_token: dict[str, str] = {}
    so_by_token: dict[str, str] = {}
    for row in sources:
        po_ref = effective_po_reference(row.po_reference)
        if po_ref and is_plausible_po_reference(po_ref):
            po_by_token.setdefault(normalize_po_link_token(po_ref), po_ref)
        so_ref = resolve_so_reference_from_invoice(row)
        if so_ref and is_plausible_so_reference(so_ref):
            so_by_token.setdefault(normalize_so_link_token(so_ref), so_ref)

    if not po_by_token and not so_by_token:
        return response

    seen = _linked_invoice_ids(response)
    seen.add(anchor.id)
    extra: list[DossierLinkedDocumentResponse] = []

    for po_ref in po_by_token.values():
        for row in await fetch_invoices_by_po_reference_token(
            session,
            tenant_id=anchor.tenant_id,
            po_ref=po_ref,
            exclude_id=anchor.id,
            linkage_cache=linkage_cache,
        ):
            if row.id in seen:
                continue
            extra.append(
                _reference_linked_document(
                    row,
                    reference_label=po_ref,
                    link_kind="po_reference",
                    document_types=document_types,
                    linkage_detail=(
                        f"Linked on {po_ref} (via invoice no {invoice_no})"
                    ),
                )
            )
            seen.add(row.id)

    for so_ref in so_by_token.values():
        for row in await fetch_invoices_by_so_reference_token(
            session,
            tenant_id=anchor.tenant_id,
            so_ref=so_ref,
            exclude_id=anchor.id,
            linkage_cache=linkage_cache,
        ):
            if row.id in seen:
                continue
            extra.append(
                _reference_linked_document(
                    row,
                    reference_label=so_ref,
                    link_kind="so_reference",
                    document_types=document_types,
                    linkage_detail=(
                        f"Linked on {so_ref} (via invoice no {invoice_no})"
                    ),
                )
            )
            seen.add(row.id)

    if not extra:
        return response

    return response.model_copy(
        update={"documents": list(response.documents) + extra},
    )


def dossier_counterparty_label(route_target: str | None) -> str:
    side = counterparty_side_for_route(route_target)
    if side == "customer":
        return "Customer"
    if side == "vendor":
        return "Vendor"
    return "Counterparty"


def dossier_linkage_fields(invoice: Invoice) -> tuple[str | None, str | None, str | None]:
    """Return (po_reference, so_reference, primary linkage key) for dossier summary."""
    so_ref = resolve_so_reference_from_invoice(invoice)
    raw_po = effective_po_reference(invoice.po_reference)
    route = (invoice.route_target or "").strip()
    invoice_no = (invoice.invoice_no or "").strip() or None

    if route == ROUTE_SALES:
        po_display = (
            raw_po
            if raw_po
            and is_plausible_po_reference(raw_po)
            and not is_plausible_so_reference(raw_po)
            else None
        )
        return po_display, so_ref, so_ref or invoice_no or None

    po_display = raw_po if raw_po and is_plausible_po_reference(raw_po) else None
    return po_display, so_ref, po_display or invoice_no or None


async def build_dossier_summary(
    session: AsyncSession,
    invoice: Invoice,
    logs: list[AuditLog],
    *,
    payment: Payment | None = None,
    tenant_name: str | None = None,
    compact: bool = False,
    config: RuleBookConfigPayload | None = None,
) -> DossierSummaryResponse:
    if config is None:
        config = await load_posting_config_for_tenant(session, invoice.tenant_id)
    tenant = await session.get(Tenant, invoice.tenant_id)
    institution_today = tenant_today(tenant)
    definition = resolve_definition_for_invoice(invoice, config.document_types)
    published = is_published_from_audit_logs(logs)
    pay_key, pay_detail = _payment_status_key(invoice, payment)

    pipeline = build_dossier_pipeline(
        invoice,
        logs,
        payment_status=pay_key,
        payment_detail=pay_detail,
        compact=compact,
        document_types=config.document_types,
    )
    pipeline_path = _resolve_dossier_pipeline_path(invoice, logs)
    if pipeline_path == "understood":
        pipeline = build_understood_dossier_pipeline(invoice, logs)
    fail = first_pipeline_failure(pipeline)

    linked, approval = await asyncio.gather(
        build_dossier_linked_documents(
            session,
            invoice,
            definition=definition,
            document_types=config.document_types,
        ),
        build_dossier_approval_chain(
            session,
            invoice,
            logs,
            definition=definition,
            payment=payment,
            published=published,
            pipeline_path=pipeline_path,
        ),
    )

    match_log = _latest_log(logs, "three_way_match_evaluated")
    match_log_detail = match_log.detail if match_log and isinstance(match_log.detail, dict) else None
    if not compact and pipeline_path != "understood":
        pipeline = enrich_match_pipeline_step(
            pipeline,
            match_summary=linked.match_summary,
            match_log_detail=match_log_detail,
        )
        fail = first_pipeline_failure(pipeline)
    bottleneck = fail or first_pipeline_bottleneck(pipeline)
    blocker_detail = _blocker_detail_from_step(bottleneck)
    approved_human = any(log.event == "invoice_approved" for log in logs)
    outcome, banner = _derive_outcome(
        invoice,
        logs,
        fail is not None,
        published=published,
        payment=payment,
        fail_detail=blocker_detail,
    )
    # Vault-only Understood path ends at vault — pending Archive must not surface as a blocker.
    if (
        outcome != "blocked"
        and fail is None
        and pipeline_path == "understood"
        and not vision_posting_continues(logs)
    ):
        bottleneck = None
        blocker_detail = None
    if invoice.status == InvoiceStatus.PROCESSED and published and approved_human:
        outcome = "manual_posted"
        banner = banner or "Manual post — approved before ledger posting"

    code = (invoice.document_type_code or "").strip().upper()
    suggested = (invoice.llm_suggested_dt or "").strip().upper()
    display_code = code or suggested
    pending_classify = classification_review_pending(logs)
    vision_label = _vision_document_type_label(invoice) if pipeline_path == "understood" else ""
    dt_title = _document_type_title(display_code, config.document_types) if display_code else ""
    if pipeline_path == "understood":
        # Vision path: show AI/printed type, not catalogue "Unclassified".
        document_type_title = dt_title or vision_label or "Vision document"
        classification_label = vision_label or dt_title or "Vision vaulted"
        fields = invoice.extracted_fields if isinstance(invoice.extracted_fields, dict) else {}
        vision_conf = fields.get("vision_header_confidence")
        if vision_conf is None:
            vision_conf = fields.get("confidence")
        try:
            vision_conf_f = float(vision_conf) if vision_conf is not None else None
        except (TypeError, ValueError):
            vision_conf_f = None
        classification_confidence = _confidence_pct(
            vision_conf_f
            if vision_conf_f is not None and vision_conf_f > 0
            else (invoice.document_type_confidence or invoice.llm_confidence),
            floor=True,
        )
    elif pending_classify and not code:
        document_type_title = dt_title or "Unclassified"
        classification_label = (
            f"{dt_title} (needs review)" if dt_title else "Needs classification review"
        )
        classification_confidence = _confidence_pct(invoice.llm_confidence, floor=True)
    elif dt_title:
        document_type_title = dt_title
        classification_label = dt_title
        classification_confidence = _confidence_pct(invoice.document_type_confidence)
    elif pending_classify:
        document_type_title = "Unclassified"
        classification_label = "Needs classification review"
        classification_confidence = _confidence_pct(invoice.document_type_confidence)
    else:
        document_type_title = "Unclassified"
        classification_label = (invoice.route_target or "Unclassified").replace("_", " ").title()
        classification_confidence = _confidence_pct(invoice.document_type_confidence)
    sla_label, sla_breached = _sla(invoice, today=institution_today, logs=logs)
    inv_date = invoice.invoice_date.isoformat() if invoice.invoice_date else ""
    route_target = (invoice.route_target or "").strip() or None
    po_display, so_ref, linkage_ref = dossier_linkage_fields(invoice)
    counterparty = (
        resolve_counterparty_from_invoice_context(invoice, config=config)
        or (invoice.vendor or "").strip()
        or "Unknown counterparty"
    )

    return DossierSummaryResponse(
        id=dossier_public_id(invoice),
        invoice_id=invoice.id,
        document_type_code=display_code,
        document_type_title=document_type_title,
        vendor=counterparty,
        counterparty_label=dossier_counterparty_label(route_target),
        route_target=route_target,
        buyer=(tenant_name or "Tenant").strip(),
        invoice_ref=(invoice.invoice_no or display_document_ref(invoice)).strip(),
        capture_channel=dossier_capture_channel(invoice),
        invoice_date=inv_date,
        currency=(invoice.currency or "").strip(),
        subtotal=_money(invoice.subtotal),
        tax=_money(invoice.gst),
        total=_money(invoice.total),
        classification_label=classification_label,
        classification_confidence=classification_confidence,
        po_reference=po_display,
        so_reference=so_ref,
        linkage_reference=linkage_ref,
        sla_label=sla_label,
        sla_breached=sla_breached,
        owner=_owner_from_logs(logs),
        outcome=outcome,
        outcome_banner=banner,
        blocker_stage_id=bottleneck.stage_id if bottleneck else None,
        blocker_reason=blocker_detail,
        blocker_remediation=bottleneck.remediation if bottleneck else None,
        pipeline_path=pipeline_path,
        pipeline=pipeline,
        linked_documents=linked,
        approval_chain=approval,
    )


async def resolve_invoice_for_dossier(
    session: AsyncSession,
    tenant_id: int,
    dossier_id: str,
) -> Invoice | None:
    ref_lookup, id_fallback = parse_dossier_id_token(dossier_id)
    if ref_lookup is None and id_fallback is None:
        return None

    if ref_lookup:
        for candidate in (ref_lookup, ref_lookup.upper()):
            row = (
                await session.execute(
                    select(Invoice).where(
                        Invoice.tenant_id == tenant_id,
                        Invoice.document_ref == candidate,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row

    if id_fallback is not None:
        inv = await session.get(Invoice, id_fallback)
        return inv if inv is not None and inv.tenant_id == tenant_id else None

    return None


async def list_dossier_invoices(
    session: AsyncSession,
    tenant_id: int,
    *,
    page: int,
    page_size: int,
    document_type_code: str | None = None,
    q: str | None = None,
) -> tuple[list[Invoice], int]:
    stmt = (
        select(Invoice)
        .where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.tenant_id == tenant_id)

    if document_type_code and document_type_code.strip().lower() != "all":
        code = document_type_code.strip().upper()
        stmt = stmt.where(Invoice.document_type_code == code)
        count_stmt = count_stmt.where(Invoice.document_type_code == code)

    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        filt = or_(
            Invoice.vendor.ilike(needle),
            Invoice.invoice_no.ilike(needle),
            Invoice.document_ref.ilike(needle),
            Invoice.po_reference.ilike(needle),
            Invoice.so_reference.ilike(needle),
            Invoice.document_type_code.ilike(needle),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = (await session.execute(count_stmt)).scalar() or 0
    rows = (
        await session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return list(rows), total


async def org_display_name(session: AsyncSession, tenant_id: int) -> str:
    org = await session.get(Tenant, tenant_id)
    return org.name if org and org.name else "Tenant"
