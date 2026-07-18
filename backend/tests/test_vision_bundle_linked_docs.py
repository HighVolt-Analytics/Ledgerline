"""Linked-docs API prefers vision invoice-first chain while awaiting classification."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier.vision_bundle_linkage import (
    persist_vision_bundle_snapshot,
    resolve_vision_bundle_key,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_linked_docs_vision_prefers_invoice_no_over_po(
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        invoice_no="INV-BUNDLE-1",
        po_reference="PO-SHOULD-NOT-WIN",
        document_heading="TAX INVOICE",
        extracted_fields={"canonical_document_type": "Tax Invoice"},
        raw_file_path="/tmp/a.pdf",
    )
    sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        invoice_no="INV-BUNDLE-1",
        document_heading="PACKING LIST",
        extracted_fields={"canonical_document_type": "Packing List"},
        raw_file_path="/tmp/b.pdf",
    )
    db_session.add_all([anchor, sibling])
    await db_session.flush()

    link = resolve_vision_bundle_key(anchor)
    persist_vision_bundle_snapshot(anchor, link)
    await db_session.flush()

    result = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )
    assert result.linkage_kind == "invoice_no"
    assert result.linkage_key == "INV-BUNDLE-1"
    assert result.enforce_bundle is False
    ids = {d.invoice_id for d in result.documents}
    assert anchor.id in ids
    assert sibling.id in ids
    assert any(d.is_anchor for d in result.documents)
    anchor_doc = next(d for d in result.documents if d.is_anchor)
    assert anchor_doc.label == "Tax Invoice"
    sibling_doc = next(d for d in result.documents if d.invoice_id == sibling.id)
    assert sibling_doc.label == "Packing List"


@pytest.mark.asyncio
async def test_linked_docs_vision_standalone_when_no_key(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        document_heading="Quote",
        extracted_fields={"canonical_document_type": "Quote"},
        raw_file_path="/tmp/q.pdf",
    )
    db_session.add(inv)
    await db_session.flush()
    persist_vision_bundle_snapshot(inv, resolve_vision_bundle_key(inv))
    await db_session.flush()

    result = await build_dossier_linked_documents(
        db_session,
        inv,
        definition=None,
        document_types=[],
    )
    assert result.linkage_kind == "standalone"
    assert result.enforce_bundle is False
    assert len(result.documents) == 1
    assert result.documents[0].is_anchor is True
    assert result.documents[0].label == "Quote"
    assert result.documents[0].document_type_code == ""


@pytest.mark.asyncio
async def test_linked_docs_vision_card_includes_counterparty(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="DHL Express",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        document_heading="AIR WAYBILL",
        extracted_fields={"canonical_document_type": "Air Waybill"},
        raw_file_path="/tmp/awb.pdf",
    )
    db_session.add(inv)
    await db_session.flush()
    persist_vision_bundle_snapshot(inv, resolve_vision_bundle_key(inv))
    await db_session.flush()

    result = await build_dossier_linked_documents(
        db_session,
        inv,
        definition=None,
        document_types=[],
    )
    assert result.documents[0].label == "Air Waybill"
    assert result.documents[0].counterparty == "DHL Express"


@pytest.mark.asyncio
async def test_linked_docs_vision_one_hop_harvest_po_from_invoice_no_sibling(
    db_session: AsyncSession,
) -> None:
    """INV hub + PL (same invoice_no, has PO) + GRN (PO only) → all three linked."""
    hub = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        invoice_no="INV-HOP-1",
        document_heading="TAX INVOICE",
        extracted_fields={
            "canonical_document_type": "Tax Invoice",
            "vision_bundle_kind": "invoice_no",
            "vision_bundle_key": "INV-HOP-1",
        },
        raw_file_path="/tmp/hub.pdf",
    )
    packing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        invoice_no="INV-HOP-1",
        po_reference="PO-HOP-9",
        document_heading="PACKING LIST",
        extracted_fields={"canonical_document_type": "Packing List"},
        raw_file_path="/tmp/pl.pdf",
    )
    grn = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        po_reference="PO-HOP-9",
        document_heading="GOODS RECEIVED NOTE",
        extracted_fields={"canonical_document_type": "Goods Received Note"},
        raw_file_path="/tmp/grn.pdf",
    )
    unrelated = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        currency="AUD",
        po_reference="PO-OTHER-8",
        document_heading="GOODS RECEIVED NOTE",
        extracted_fields={"canonical_document_type": "Goods Received Note"},
        raw_file_path="/tmp/other.pdf",
    )
    db_session.add_all([hub, packing, grn, unrelated])
    await db_session.flush()

    result = await build_dossier_linked_documents(
        db_session,
        hub,
        definition=None,
        document_types=[],
    )
    ids = {d.invoice_id for d in result.documents}
    assert hub.id in ids
    assert packing.id in ids
    assert grn.id in ids
    assert unrelated.id not in ids
    grn_doc = next(d for d in result.documents if d.invoice_id == grn.id)
    assert grn_doc.link_kind == "po_reference"
    assert "PO-HOP-9" in (grn_doc.linkage_detail or "")
    assert "INV-HOP-1" in (grn_doc.linkage_detail or "")
