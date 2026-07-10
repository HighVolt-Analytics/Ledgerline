"""CRUD for dossier-only manual document links."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dossier_manual_link import DossierManualLink
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.dossier import (
    DossierLinkedDocumentResponse,
    DossierLinkedDocumentsResponse,
    DossierManualLinkInfoResponse,
)
from app.services.dossier.document_ref_service import display_document_ref, dossier_public_id
from app.services.shared.file_storage import has_stored_path

_SKIP_STATUSES = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


async def list_manual_links(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchor_invoice_id: int,
) -> list[DossierManualLink]:
    rows = (
        await session.execute(
            select(DossierManualLink)
            .where(
                DossierManualLink.tenant_id == tenant_id,
                DossierManualLink.anchor_invoice_id == anchor_invoice_id,
            )
            .order_by(DossierManualLink.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def _load_invoices(
    session: AsyncSession,
    invoice_ids: set[int],
    *,
    tenant_id: uuid.UUID,
) -> dict[int, Invoice]:
    if not invoice_ids:
        return {}
    rows = (
        await session.execute(
            select(Invoice).where(
                Invoice.id.in_(invoice_ids),
                Invoice.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    return {row.id: row for row in rows}


def _dt_label(code: str, document_types: list[DocumentTypeDefinition]) -> str:
    token = (code or "").strip().upper()
    for row in document_types:
        if row.code.upper() == token:
            return row.title or row.short_title or token
    return token or "Document"


def _manual_link_info(
    link: DossierManualLink,
    linked: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> DossierManualLinkInfoResponse:
    code = (linked.document_type_code or "").strip().upper()
    return DossierManualLinkInfoResponse(
        id=link.id,
        invoice_id=linked.id,
        linked_dossier_id=dossier_public_id(linked),
        document_ref=display_document_ref(linked),
        label=_dt_label(code, document_types),
        document_type_code=code,
        has_file=has_stored_path(linked.raw_file_path),
    )


def _ad_hoc_manual_document(
    link: DossierManualLink,
    linked: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> DossierLinkedDocumentResponse:
    code = (linked.document_type_code or "").strip().upper()
    label = _dt_label(code, document_types)
    return DossierLinkedDocumentResponse(
        id=f"manual-{link.id}",
        document_type_code=code,
        label=label,
        document_ref=display_document_ref(linked),
        present=True,
        requirement="advisory",
        source="manual",
        linked_dossier_id=dossier_public_id(linked),
        invoice_id=linked.id,
        is_anchor=False,
        has_file=has_stored_path(linked.raw_file_path),
        linkage_detail="Manually linked — not used for validation",
        link_kind="manual",
        manual_link_id=link.id,
    )


def _dt_code_from_slot_id(slot_id: str) -> str | None:
    token = (slot_id or "").strip()
    if token.startswith("DT-") and "-bundle" in token:
        return token.split("-bundle", 1)[0].upper()
    return None


def _pick_single_slot(
    candidates: list[DossierLinkedDocumentResponse],
) -> DossierLinkedDocumentResponse | None:
    if len(candidates) == 1:
        return candidates[0]
    mandatory = [doc for doc in candidates if doc.requirement == "mandatory"]
    if len(mandatory) == 1:
        return mandatory[0]
    return None


def _find_slot_for_manual_link(
    link: DossierManualLink,
    linked: Invoice,
    documents: list[DossierLinkedDocumentResponse],
) -> DossierLinkedDocumentResponse | None:
    eligible = [
        doc for doc in documents if not doc.is_anchor and doc.manual_link is None
    ]
    linked_code = (linked.document_type_code or "").strip().upper()
    if linked_code:
        match = _pick_single_slot(
            [
                doc
                for doc in eligible
                if (doc.document_type_code or "").strip().upper() == linked_code
            ]
        )
        if match is not None:
            return match

    stale_code = _dt_code_from_slot_id(link.slot_id or "")
    if stale_code:
        match = _pick_single_slot(
            [
                doc
                for doc in eligible
                if (doc.document_type_code or "").strip().upper() == stale_code
            ]
        )
        if match is not None:
            return match
    return None


def _apply_slot_overlay(
    doc: DossierLinkedDocumentResponse,
    link: DossierManualLink,
    linked: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> DossierLinkedDocumentResponse:
    return doc.model_copy(
        update={
            "manual_link": _manual_link_info(link, linked, document_types),
            "manual_link_id": link.id,
        }
    )


async def apply_manual_links(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchor_invoice_id: int,
    response: DossierLinkedDocumentsResponse,
    document_types: list[DocumentTypeDefinition],
) -> DossierLinkedDocumentsResponse:
    links = await list_manual_links(
        session,
        tenant_id=tenant_id,
        anchor_invoice_id=anchor_invoice_id,
    )
    if not links:
        return response

    linked_ids = {link.linked_invoice_id for link in links}
    invoices = await _load_invoices(session, linked_ids, tenant_id=tenant_id)

    slot_links_by_id = {link.slot_id: link for link in links if link.slot_id}
    matched_link_ids: set[int] = set()

    documents: list[DossierLinkedDocumentResponse] = []
    for doc in response.documents:
        slot_link = slot_links_by_id.get(doc.id)
        if slot_link is None:
            documents.append(doc)
            continue
        linked = invoices.get(slot_link.linked_invoice_id)
        if linked is None:
            documents.append(doc)
            continue
        matched_link_ids.add(slot_link.id)
        documents.append(_apply_slot_overlay(doc, slot_link, linked, document_types))

    for link in links:
        if link.id in matched_link_ids or not link.slot_id:
            continue
        linked = invoices.get(link.linked_invoice_id)
        if linked is None:
            continue
        target = _find_slot_for_manual_link(link, linked, documents)
        if target is None:
            continue
        matched_link_ids.add(link.id)
        documents = [
            _apply_slot_overlay(doc, link, linked, document_types)
            if doc.id == target.id
            else doc
            for doc in documents
        ]

    ad_hoc: list[DossierLinkedDocumentResponse] = []
    for link in links:
        if link.id in matched_link_ids:
            continue
        linked = invoices.get(link.linked_invoice_id)
        if linked is None:
            continue
        ad_hoc.append(_ad_hoc_manual_document(link, linked, document_types))

    return response.model_copy(update={"documents": documents + ad_hoc})


def _resolve_slot_id(
    slot_id: str | None,
    linked: Invoice,
    documents: list[DossierLinkedDocumentResponse],
) -> str | None:
    token = (slot_id or "").strip()
    if not token:
        return None
    if any(doc.id == token for doc in documents if not doc.is_anchor):
        return token

    linked_code = (linked.document_type_code or "").strip().upper()
    if linked_code:
        match = _pick_single_slot(
            [
                doc
                for doc in documents
                if not doc.is_anchor
                and (doc.document_type_code or "").strip().upper() == linked_code
            ]
        )
        if match is not None:
            return match.id

    stale_code = _dt_code_from_slot_id(token)
    if stale_code:
        match = _pick_single_slot(
            [
                doc
                for doc in documents
                if not doc.is_anchor
                and (doc.document_type_code or "").strip().upper() == stale_code
            ]
        )
        if match is not None:
            return match.id

    return token


async def create_manual_link(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchor_invoice_id: int,
    linked_invoice_id: int,
    slot_id: str | None = None,
    created_by_user_id: int | None = None,
) -> DossierManualLink:
    if linked_invoice_id == anchor_invoice_id:
        raise HTTPException(400, "Cannot link a dossier to itself")

    anchor = await session.get(Invoice, anchor_invoice_id)
    if anchor is None or anchor.tenant_id != tenant_id:
        raise HTTPException(404, "Dossier not found")

    linked = await session.get(Invoice, linked_invoice_id)
    if linked is None or linked.tenant_id != tenant_id:
        raise HTTPException(404, "Linked document not found")
    if linked.status in _SKIP_STATUSES:
        raise HTTPException(400, "Cannot link rejected or duplicate documents")

    existing = (
        await session.execute(
            select(DossierManualLink).where(
                DossierManualLink.tenant_id == tenant_id,
                DossierManualLink.anchor_invoice_id == anchor_invoice_id,
                DossierManualLink.linked_invoice_id == linked_invoice_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Document is already manually linked")

    resolved_slot_id = slot_id
    if slot_id:
        from app.services.classification.document_type_playbook_service import (
            resolve_definition_for_invoice,
        )
        from app.services.dossier.dossier_linked_documents_service import (
            build_dossier_linked_documents,
        )
        from app.services.invoice.invoice_evaluation_service import (
            load_posting_config_for_tenant,
        )

        config = await load_posting_config_for_tenant(session, tenant_id)
        definition = resolve_definition_for_invoice(anchor, config.document_types)
        linked_docs = await build_dossier_linked_documents(
            session,
            anchor,
            definition=definition,
            document_types=config.document_types,
        )
        resolved_slot_id = _resolve_slot_id(
            slot_id,
            linked,
            linked_docs.documents,
        )
        if resolved_slot_id and not any(
            doc.id == resolved_slot_id for doc in linked_docs.documents if not doc.is_anchor
        ):
            # Keep stale slot_id — apply_manual_links will DT-match or ad-hoc append.
            resolved_slot_id = slot_id.strip()

        slot_taken = (
            await session.execute(
                select(DossierManualLink).where(
                    DossierManualLink.tenant_id == tenant_id,
                    DossierManualLink.anchor_invoice_id == anchor_invoice_id,
                    DossierManualLink.slot_id == resolved_slot_id,
                )
            )
        ).scalar_one_or_none()
        if slot_taken is not None:
            raise HTTPException(409, "This bundle slot already has a manual link")

    row = DossierManualLink(
        tenant_id=tenant_id,
        anchor_invoice_id=anchor_invoice_id,
        linked_invoice_id=linked_invoice_id,
        slot_id=(resolved_slot_id or "").strip() or None,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def delete_manual_link(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    anchor_invoice_id: int,
    link_id: int,
) -> bool:
    row = await session.get(DossierManualLink, link_id)
    if row is None:
        return False
    if row.tenant_id != tenant_id or row.anchor_invoice_id != anchor_invoice_id:
        return False
    await session.delete(row)
    await session.flush()
    return True
