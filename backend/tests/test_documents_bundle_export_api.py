"""Documents bundle CSV export API tests."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.line_item import LineItem
from app.schemas.dossier import DossierLinkedDocumentsResponse, DossierMatchSummaryResponse
from app.services.audit.audit_export_service import (
    collect_linked_doc_entries,
    format_linked_docs_export,
    linked_docs_by_dt_code,
    vault_view_path,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase.purchase_match_service import sync_purchase_order_from_invoice
from app.services.reports.documents_bundle_export_service import (
    _match_flags,
    build_documents_bundle_export,
)
from app.tenant_ids import TESTING_TENANT_UUID
from tests.test_audit_export_api import assert_csv_hyperlink


def _read_csv(text: str) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(text)))
    assert rows
    return rows[0], rows[1:]


def test_match_flags_yes_no_only() -> None:
    linked = DossierLinkedDocumentsResponse(
        linkage_kind="po_reference",
        linkage_label="PO reference",
        enforce_bundle=True,
        match_summary=DossierMatchSummaryResponse(
            status="3-Way Match",
            currency="AUD",
            po_value=100.0,
            invoice_total=110.0,
        ),
    )
    two, three, universal = _match_flags(linked)
    assert two == "No"
    assert three == "Yes"
    assert universal == "No"


@pytest.mark.asyncio
async def test_documents_bundle_export_excludes_non_posting_documents(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Supplier",
                document_type_code="DT-01",
                invoice_no="INV-POST-1",
                invoice_date=date(2026, 5, 10),
                status=InvoiceStatus.PROCESSED,
                file_hash="bundle-posting-yes",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Supplier",
                document_type_code="DT-02",
                invoice_no="PO-SUPPORT-1",
                invoice_date=date(2026, 5, 10),
                status=InvoiceStatus.PROCESSED,
                file_hash="bundle-posting-no",
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-05-01&date_to=2026-05-31"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    assert "2 way match" in header
    assert "3 way match" in header
    assert "Universal match" in header
    assert "PO goods invoice" in header
    assert "GRN (supporting)" in header

    invoice_nos = {row[header.index("Invoice no.")] for row in data}
    assert "INV-POST-1" in invoice_nos
    assert "PO-SUPPORT-1" not in invoice_nos

    posting_row = next(row for row in data if row[header.index("Invoice no.")] == "INV-POST-1")
    assert posting_row[header.index("Class")] == "Transactional"
    assert posting_row[header.index("Posting")] == "Yes"
    assert posting_row[header.index("2 way match")] == "No"
    assert posting_row[header.index("3 way match")] == "No"
    assert posting_row[header.index("Universal match")] == "No"


@pytest.mark.asyncio
async def test_documents_bundle_export_three_way_and_linked_po_hyperlink(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        document_type_code="DT-02",
        po_reference="PO-BUNDLE-1",
        invoice_no="PO-BUNDLE-1",
        invoice_date=date(2026, 5, 12),
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("200.00"),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-po-doc",
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    await sync_purchase_order_from_invoice(db_session, po_doc)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        document_type_code="DT-01",
        po_reference="PO-BUNDLE-1",
        invoice_no="INV-BUNDLE-1",
        invoice_date=date(2026, 5, 15),
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("200.00"),
        gst=Decimal("20.00"),
        total=Decimal("220.00"),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-inv-doc",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, inv)
    assert po is not None
    await db_session.commit()

    grn_res = await client.post(
        f"/api/purchases/{po.id}/grn",
        json={"grn_qty": 4, "receiver": "Warehouse A", "condition_note": "Good"},
    )
    assert grn_res.status_code == 200
    assert grn_res.json()["data"]["match"]["status"] == "3-Way Match"

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-05-01&date_to=2026-05-31"
    )
    assert res.status_code == 200
    assert "documents_bundle_2026-05.csv" in res.headers.get("content-disposition", "")

    header, data = _read_csv(res.text)
    row = next(r for r in data if r[header.index("Invoice no.")] == "INV-BUNDLE-1")
    assert row[header.index("3 way match")] == "Yes"
    assert row[header.index("2 way match")] == "No"
    assert row[header.index("Universal match")] == "No"

    po_col = header.index("PO (supporting)")
    assert_csv_hyperlink(row[po_col], url=vault_view_path(po_doc.id))


@pytest.mark.asyncio
async def test_documents_bundle_export_universal_match_yes(
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-01",
        invoice_no="SHARED-INV-77",
        invoice_date=date(2026, 6, 3),
        file_hash="bundle-universal-anchor",
    )
    sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-26",
        invoice_no="SHARED-INV-77",
        invoice_date=date(2026, 6, 3),
        file_hash="bundle-universal-sibling",
    )
    db_session.add_all([anchor, sibling])
    await db_session.commit()

    payload = await build_documents_bundle_export(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 30),
    )
    header, data = _read_csv(payload.csv_text)
    row = next(r for r in data if r[header.index("Invoice no.")] == "SHARED-INV-77")
    assert row[header.index("Universal match")] == "Yes"
    assert row[header.index("3 way match")] == "No"
    assert row[header.index("2 way match")] == "No"


def test_linked_docs_helpers_still_support_audit_export() -> None:
    from app.schemas.dossier import DossierLinkedDocumentResponse

    linked = DossierLinkedDocumentsResponse(
        linkage_kind="invoice_no",
        linkage_label="Invoice no.",
        enforce_bundle=False,
        documents=[
            DossierLinkedDocumentResponse(
                id="anchor",
                document_type_code="DT-01",
                label="Anchor",
                present=True,
                requirement="mandatory",
                is_anchor=True,
                invoice_id=1,
            ),
            DossierLinkedDocumentResponse(
                id="sibling",
                document_type_code="DT-26",
                label="Sibling",
                document_ref="DOC-9",
                present=True,
                requirement="advisory",
                link_kind="invoice_no",
                invoice_id=9,
            ),
        ],
    )
    entries = collect_linked_doc_entries(1, linked)
    assert len(entries) == 1
    assert entries[0].invoice_id == 9

    audit_cell = format_linked_docs_export(1, linked)
    assert "DT-26:DOC-9" in audit_cell

    by_dt = linked_docs_by_dt_code(1, linked, label_fn="bundle")
    assert "DT-26" in by_dt
    assert "DOC-9" in by_dt["DT-26"]
