"""Linked-documents panel — document type must reflect invoice classification."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier_linked_documents_service import build_dossier_linked_documents
from tests.conftest import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_standalone_unclassified_does_not_default_to_dt01(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        status=InvoiceStatus.EXCEPTION,
        document_type_code=None,
        file_hash="linked-doc-unclassified",
    )
    db_session.add(inv)
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        inv,
        definition=None,
        document_types=[],
    )

    assert linked.linkage_kind == "standalone"
    assert len(linked.documents) == 1
    anchor = linked.documents[0]
    assert anchor.is_anchor is True
    assert anchor.document_type_code == ""
    assert anchor.label == "Unclassified"


@pytest.mark.asyncio
async def test_standalone_classified_uses_invoice_document_type(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-03",
        file_hash="linked-doc-classified",
    )
    db_session.add(inv)
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        inv,
        definition=None,
        document_types=[],
    )

    anchor = linked.documents[0]
    assert anchor.is_anchor is True
    assert anchor.document_type_code == "DT-03"
    assert anchor.label == "DT-03"


@pytest.mark.asyncio
async def test_invoice_no_siblings_appended_to_linked_documents(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        invoice_no="260671582",
        file_hash="linked-anchor-inv-no",
    )
    coo = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-26",
        invoice_no="260671582",
        file_hash="linked-coo-inv-no",
    )
    bl = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-27",
        invoice_no="260671582",
        file_hash="linked-bl-inv-no",
    )
    db_session.add_all([anchor, coo, bl])
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )

    invoice_no_docs = [d for d in linked.documents if d.link_kind == "invoice_no"]
    assert len(invoice_no_docs) == 2
    ids = {d.invoice_id for d in invoice_no_docs}
    assert ids == {coo.id, bl.id}
    assert all(d.invoice_no == "260671582" for d in invoice_no_docs)
    assert all(d.present is True for d in invoice_no_docs)


@pytest.mark.asyncio
async def test_invoice_no_linked_docs_deduplicate_existing_bundle_member(
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        invoice_no="INV-SHARED",
        po_reference="PO-9001",
        purchase_document_type="invoice",
        file_hash="linked-po-anchor",
    )
    po = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Supplier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-14",
        invoice_no="INV-SHARED",
        po_reference="PO-9001",
        purchase_document_type="po",
        file_hash="linked-po-member",
    )
    db_session.add_all([anchor, po])
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )

    po_rows = [d for d in linked.documents if d.invoice_id == po.id]
    assert len(po_rows) == 1
