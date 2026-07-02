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
async def test_invoice_no_bundle_is_advisory_and_automatic(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        invoice_no="SHARED-INV-001",
        file_hash="inv-no-bundle-anchor",
    )
    sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-26",
        invoice_no="SHARED-INV-001",
        file_hash="inv-no-bundle-sibling",
    )
    db_session.add_all([anchor, sibling])
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )

    assert linked.linkage_kind == "invoice_no"
    assert linked.linkage_key == "SHARED-INV-001"
    assert linked.enforce_bundle is False
    assert len(linked.documents) == 2
    assert all(doc.requirement == "advisory" for doc in linked.documents)
    assert all(doc.present for doc in linked.documents)


@pytest.mark.asyncio
async def test_playbook_bundle_satisfied_by_invoice_no_without_po(db_session: AsyncSession) -> None:
    from app.services.document_type_playbook_service import missing_bundle_dt_codes

    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        invoice_no="INV-BUNDLE-900",
        file_hash="playbook-inv-no-anchor",
    )
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Supplier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-14",
        invoice_no="INV-BUNDLE-900",
        file_hash="playbook-inv-no-po",
    )
    db_session.add_all([anchor, po_doc])
    await db_session.flush()

    missing = await missing_bundle_dt_codes(
        db_session,
        invoice=anchor,
        dt_codes=["DT-14"],
    )
    assert missing == []


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


@pytest.mark.asyncio
async def test_sales_so_dossier_links_so_and_dn_members(db_session: AsyncSession) -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    def _dt(**kwargs) -> DocumentTypeDefinition:
        base = dict(
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="test",
        )
        base.update(kwargs)
        return DocumentTypeDefinition(**base)

    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-07",
        route_target="Sales Management",
        so_reference="SO-DEMO-100",
        sales_document_type="so",
        file_hash="linked-sales-so",
    )
    dn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-08",
        route_target="Sales Management",
        so_reference="SO-DEMO-100",
        sales_document_type="dn",
        file_hash="linked-sales-dn",
    )
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        status=InvoiceStatus.EXCEPTION,
        document_type_code="DT-06",
        route_target="Sales Management",
        po_reference="SO-DEMO-100",
        so_reference="SO-DEMO-100",
        sales_document_type="invoice",
        invoice_no="INV-9001",
        file_hash="linked-sales-inv",
    )
    db_session.add_all([so_doc, dn_doc, anchor])
    await db_session.flush()

    document_types = [
        _dt(
            code="DT-06",
            title="Customer invoice",
            short_title="Customer invoice",
            route_target="Sales Management",
            playbook_profile="ar_goods",
            bundle_mandatory=["DT-07", "DT-08"],
        ),
        _dt(
            code="DT-07",
            title="Sales order",
            short_title="Sales order",
            sales_bundle_role="so",
        ),
        _dt(
            code="DT-08",
            title="Delivery note",
            short_title="Delivery note (outbound)",
            sales_bundle_role="dn",
        ),
    ]
    definition = document_types[0]

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=definition,
        document_types=document_types,
    )

    assert linked.linkage_kind == "so_reference"
    assert linked.linkage_key == "SO-DEMO-100"
    assert len(linked.documents) == 3
    by_role = {d.sales_bundle_role: d for d in linked.documents}
    assert by_role["so"].present is True
    assert by_role["so"].invoice_id == so_doc.id
    assert by_role["dn"].present is True
    assert by_role["dn"].invoice_id == dn_doc.id
    assert by_role["invoice"].present is True
    assert by_role["invoice"].invoice_id == anchor.id
    assert by_role["so"].document_type_code == "DT-07"
    assert by_role["dn"].document_type_code == "DT-08"
