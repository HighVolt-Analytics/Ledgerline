"""Tests for dossier manual document links."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dossier_manual_link import DossierManualLink
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_ref_service import assign_document_ref
from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
from app.services.dossier.dossier_manual_link_service import apply_manual_links, create_manual_link
from app.schemas.dossier import DossierLinkedDocumentResponse, DossierLinkedDocumentsResponse
from tests.conftest import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_manual_link_on_bundle_slot(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-10",
        file_hash="anchor-import",
    )
    bl = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-27",
        invoice_no="BL-4402",
        file_hash="bl-doc",
    )
    db_session.add_all([anchor, bl])
    await db_session.flush()
    await assign_document_ref(db_session, bl)

    await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=bl.id,
        slot_id="DT-27-bundle",
    )

    base = DossierLinkedDocumentsResponse(
        linkage_kind="shipment_ref",
        linkage_key="SHIP-1",
        linkage_label="Import dossier",
        enforce_bundle=True,
        documents=[
            DossierLinkedDocumentResponse(
                id="DT-27-bundle",
                document_type_code="DT-27",
                label="Bill of lading",
                present=False,
                requirement="mandatory",
            )
        ],
    )
    linked = await apply_manual_links(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        response=base,
        document_types=[],
    )

    slot = linked.documents[0]
    assert slot.present is False
    assert slot.manual_link is not None
    assert slot.manual_link_id is not None
    assert slot.manual_link.invoice_id == bl.id
    assert slot.manual_link.document_ref == bl.document_ref


@pytest.mark.asyncio
async def test_orphaned_slot_id_falls_back_by_dt_code(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-10",
        file_hash="anchor-orphan-slot",
    )
    bl = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-27",
        invoice_no="BL-ORPHAN",
        file_hash="bl-orphan",
    )
    db_session.add_all([anchor, bl])
    await db_session.flush()
    await assign_document_ref(db_session, bl)

    await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=bl.id,
        slot_id="DT-27-bundle",
    )

    base = DossierLinkedDocumentsResponse(
        linkage_kind="so_reference",
        linkage_key="SO-9",
        linkage_label="SO reference",
        enforce_bundle=True,
        documents=[
            DossierLinkedDocumentResponse(
                id="DT-27-bundle-so",
                document_type_code="DT-27",
                label="Bill of lading",
                present=False,
                requirement="mandatory",
            )
        ],
    )
    linked = await apply_manual_links(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        response=base,
        document_types=[],
    )

    slot = linked.documents[0]
    assert slot.manual_link is not None
    assert slot.manual_link.invoice_id == bl.id
    assert slot.manual_link_id is not None


@pytest.mark.asyncio
async def test_orphaned_slot_id_appends_ad_hoc_when_no_dt_match(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-10",
        file_hash="anchor-ad-hoc-fallback",
    )
    support = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-06",
        invoice_no="PACK-ORPHAN",
        file_hash="pack-orphan",
    )
    db_session.add_all([anchor, support])
    await db_session.flush()

    await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=support.id,
        slot_id="DT-99-bundle",
    )

    base = DossierLinkedDocumentsResponse(
        linkage_kind="standalone",
        linkage_label="Standalone",
        enforce_bundle=False,
        documents=[
            DossierLinkedDocumentResponse(
                id="DT-15-bundle-grn",
                document_type_code="DT-15",
                label="GRN",
                present=False,
                requirement="mandatory",
            )
        ],
    )
    linked = await apply_manual_links(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        response=base,
        document_types=[],
    )

    manual = next(doc for doc in linked.documents if doc.link_kind == "manual")
    assert manual.invoice_id == support.id
    assert manual.manual_link_id is not None


@pytest.mark.asyncio
async def test_ad_hoc_manual_link_appended(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-03",
        file_hash="anchor-standalone",
    )
    support = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-02",
        file_hash="support-doc",
    )
    db_session.add_all([anchor, support])
    await db_session.flush()

    await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=support.id,
    )

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )

    manual = next(doc for doc in linked.documents if doc.link_kind == "manual")
    assert manual.present is True
    assert manual.requirement == "advisory"
    assert manual.invoice_id == support.id
    assert manual.manual_link is not None
    assert manual.manual_link.invoice_id == support.id
    assert manual.manual_link_id is not None


@pytest.mark.asyncio
async def test_manual_link_api_round_trip(client: AsyncClient, db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Anchor Co",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-03",
        file_hash="api-anchor",
    )
    other = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Other Co",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-02",
        invoice_no="PACK-1",
        file_hash="api-other",
    )
    db_session.add_all([anchor, other])
    await db_session.flush()
    await assign_document_ref(db_session, anchor)
    await assign_document_ref(db_session, other)

    dossier_id = anchor.document_ref
    res = await client.post(
        f"/api/dossiers/{dossier_id}/manual-links",
        json={"linked_invoice_id": other.id},
    )
    assert res.status_code == 200
    docs = res.json()["data"]["linked_documents"]["documents"]
    assert any(doc.get("link_kind") == "manual" for doc in docs)

    link_id = next(doc["manual_link_id"] for doc in docs if doc.get("manual_link_id"))
    del_res = await client.delete(f"/api/dossiers/{dossier_id}/manual-links/{link_id}")
    assert del_res.status_code == 200
    after = del_res.json()["data"]["linked_documents"]["documents"]
    assert not any(doc.get("link_kind") == "manual" for doc in after)


@pytest.mark.asyncio
async def test_manual_link_ignores_missing_created_by_user(
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Anchor Co",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="Commercial Invoice",
        file_hash="vision-anchor-user",
    )
    other = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Other Co",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="Packing List",
        file_hash="vision-other-user",
    )
    db_session.add_all([anchor, other])
    await db_session.flush()

    row = await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=other.id,
        created_by_user_id=9_999_999,
    )
    assert row.created_by_user_id is None


@pytest.mark.asyncio
async def test_vision_soft_bundle_manual_link_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vision Importer",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="Commercial Invoice",
        invoice_no="SI-VISION-1",
        file_hash="vision-api-anchor",
        extracted_fields={
            "canonical_document_type": "Commercial Invoice",
            "invoice_no": "SI-VISION-1",
        },
    )
    other = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vision Carrier",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="awaiting_classification",
        document_heading="Air Waybill",
        file_hash="vision-api-other",
    )
    db_session.add_all([anchor, other])
    await db_session.flush()
    await assign_document_ref(db_session, anchor)
    await assign_document_ref(db_session, other)

    dossier_id = anchor.document_ref
    res = await client.post(
        f"/api/dossiers/{dossier_id}/manual-links",
        json={"linked_invoice_id": other.id, "slot_id": None},
    )
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body.get("pipeline_path") in ("understood", "unknown", "not_understood")
    docs = body["linked_documents"]["documents"]
    manual = next(doc for doc in docs if doc.get("link_kind") == "manual")
    assert manual["invoice_id"] == other.id
    assert manual.get("manual_link") is not None
    assert manual["manual_link"]["invoice_id"] == other.id


@pytest.mark.asyncio
async def test_manual_link_does_not_change_po_reference(db_session: AsyncSession) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        po_reference="PO-100",
        file_hash="po-anchor",
    )
    other = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-27",
        po_reference=None,
        file_hash="unlinked-bl",
    )
    db_session.add_all([anchor, other])
    await db_session.flush()

    await create_manual_link(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        anchor_invoice_id=anchor.id,
        linked_invoice_id=other.id,
    )
    await db_session.refresh(other)

    assert other.po_reference is None
    count = (
        await db_session.execute(
            select(DossierManualLink).where(DossierManualLink.anchor_invoice_id == anchor.id)
        )
    ).scalars().all()
    assert len(count) == 1
