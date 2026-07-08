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
    bundle_dt_cells_by_code,
)
from app.tenant_ids import TESTING_TENANT_UUID
from tests.test_audit_export_api import assert_csv_hyperlink


def _read_csv(text: str) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(text)))
    assert rows
    return rows[0], rows[1:]


def _invoice_no_from_cell(cell: str) -> str:
    if cell.startswith("=HYPERLINK("):
        label_start = cell.rfind(',"')
        if label_start >= 0:
            return cell[label_start + 2 : -2]
    if " | " in cell:
        return cell.split(" | ", 1)[0]
    return cell


def _invoice_nos_from_rows(header: list[str], data: list[list[str]]) -> set[str]:
    col = header.index("Invoice no.")
    return {_invoice_no_from_cell(row[col]) for row in data}


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
    assert "Invoice date" in header
    assert "Counterparty" in header
    assert "Linkage" in header
    assert "PO goods invoice" in header
    assert "GRN (supporting)" in header

    invoice_nos = _invoice_nos_from_rows(header, data)
    assert "INV-POST-1" in invoice_nos
    assert "PO-SUPPORT-1" not in invoice_nos

    posting_row = next(
        row for row in data if _invoice_no_from_cell(row[header.index("Invoice no.")]) == "INV-POST-1"
    )
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
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-BUNDLE-1"
    )
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
        document_type_code="DT-06",
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
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "SHARED-INV-77"
    )
    assert row[header.index("Universal match")] == "Yes"
    assert row[header.index("3 way match")] == "No"
    assert row[header.index("2 way match")] == "No"


@pytest.mark.asyncio
async def test_documents_bundle_export_with_empty_tenant_document_types(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from app.models.tenant_rule_book_config import TenantRuleBookConfig
    from app.services.rule_book.rule_book_config_io import clear_posting_config_cache

    row = await db_session.get(TenantRuleBookConfig, TESTING_TENANT_UUID)
    assert row is not None
    row.config = {**row.config, "document_types": []}
    await db_session.flush()
    clear_posting_config_cache()

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Supplier",
            document_type_code="DT-01",
            invoice_no="INV-CATALOG-FALLBACK",
            invoice_date=date(2026, 7, 8),
            status=InvoiceStatus.PROCESSED,
            file_hash="bundle-empty-catalogue",
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-07-01&date_to=2026-07-31"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    assert len(header) == 15
    assert data == []


@pytest.mark.asyncio
async def test_documents_bundle_export_dual_linkage_invoice_no_and_po_reference(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Buyer",
        document_type_code="DT-01",
        invoice_no="INV-DUAL-100",
        po_reference="PO-DUAL-99",
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        route_target=ROUTE_PURCHASE,
        invoice_date=date(2026, 7, 10),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-dual-anchor",
    )
    invoice_no_sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        document_type_code="DT-06",
        invoice_no="INV-DUAL-100",
        po_reference="OTHER-PO",
        invoice_date=date(2026, 7, 9),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-dual-inv-sibling",
    )
    po_sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Supplier",
        document_type_code="DT-02",
        invoice_no="PO-DOC-ONLY",
        po_reference="PO-DUAL-99",
        purchase_document_type=PurchaseDocumentType.PO.value,
        invoice_date=date(2026, 7, 8),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-dual-po-sibling",
    )
    db_session.add_all([anchor, invoice_no_sibling, po_sibling])
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-07-01&date_to=2026-07-31"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-DUAL-100"
    )

    proforma_col = header.index("Proforma / advance")
    po_col = header.index("PO (supporting)")
    assert_csv_hyperlink(row[proforma_col], url=vault_view_path(invoice_no_sibling.id))
    assert_csv_hyperlink(row[po_col], url=vault_view_path(po_sibling.id))


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


def test_bundle_dt_cells_marks_missing_mandatory_slots() -> None:
    from app.schemas.dossier import DossierLinkedDocumentResponse

    linked = DossierLinkedDocumentsResponse(
        linkage_kind="po_reference",
        linkage_label="PO reference",
        enforce_bundle=True,
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
                id="po-slot",
                document_type_code="DT-02",
                label="PO",
                present=False,
                requirement="mandatory",
            ),
            DossierLinkedDocumentResponse(
                id="grn-slot",
                document_type_code="DT-03",
                label="GRN",
                present=False,
                requirement="mandatory",
            ),
        ],
    )
    cells = bundle_dt_cells_by_code(1, linked, ["DT-02", "DT-03", "DT-26"])
    assert cells["DT-02"] == "Missing"
    assert cells["DT-03"] == "Missing"
    assert cells["DT-26"] == ""


def test_bundle_dt_cells_marks_advisory_slots() -> None:
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
                id="advisory",
                document_type_code="DT-26",
                label="Customer invoice",
                present=False,
                requirement="advisory",
            ),
        ],
    )
    cells = bundle_dt_cells_by_code(1, linked, ["DT-26"])
    assert cells["DT-26"] == "Advisory"


@pytest.mark.asyncio
async def test_documents_bundle_export_missing_mandatory_in_csv(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Supplier",
            document_type_code="DT-01",
            invoice_no="INV-MISSING-BUNDLE",
            invoice_date=date(2026, 8, 1),
            status=InvoiceStatus.PROCESSED,
            file_hash="bundle-missing-mandatory",
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-08-01&date_to=2026-08-31"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-MISSING-BUNDLE"
    )
    assert row[header.index("PO (supporting)")] == "Missing"
    assert row[header.index("GRN (supporting)")] == "Missing"


@pytest.mark.asyncio
async def test_documents_bundle_export_plain_format(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Plain Vendor",
        document_type_code="DT-01",
        invoice_no="INV-PLAIN-1",
        invoice_date=date(2026, 8, 5),
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-plain-format",
    )
    db_session.add(inv)
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-08-01&date_to=2026-08-31&format=plain"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-PLAIN-1"
    )
    inv_cell = row[header.index("Invoice no.")]
    assert not inv_cell.startswith("=HYPERLINK(")
    assert "INV-PLAIN-1 |" in inv_cell
    assert "/vault?invoice=" in inv_cell


@pytest.mark.asyncio
async def test_documents_bundle_export_includes_all_org_document_types(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

    org_types = await load_config_for_tenant(db_session, TESTING_TENANT_UUID)

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Supplier",
            document_type_code="DT-01",
            invoice_no="INV-FULL-COLS",
            invoice_date=date(2026, 8, 10),
            status=InvoiceStatus.PROCESSED,
            file_hash="bundle-full-cols",
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-08-01&date_to=2026-08-31"
    )
    assert res.status_code == 200
    header, _ = _read_csv(res.text)
    fixed_count = 15
    dt_column_count = len(header) - fixed_count
    assert dt_column_count == len(org_types.document_types)
    shipped_only_codes = {"DT-14", "DT-15", "DT-26", "DT-27", "DT-28"}
    header_labels = set(header[fixed_count:])
    for code in shipped_only_codes:
        assert not any(code in label for label in header_labels)


@pytest.mark.asyncio
async def test_documents_bundle_export_includes_custom_tenant_document_type_column(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from app.models.tenant_rule_book_config import TenantRuleBookConfig
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
    from app.services.rule_book.rule_book_config_io import clear_posting_config_cache

    base_config = await load_config_for_tenant(db_session, TESTING_TENANT_UUID)
    dt01 = next(dt for dt in base_config.document_types if dt.code == "DT-01")
    custom_dt = DocumentTypeDefinition(
        code="DT-99",
        title="Custom freight note",
        short_title="Freight note",
        klass="Supporting",
        posting="No",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        route_target="Vault",
        classifier=DocumentTypeClassifier(enabled=False, priority=100, confidence=0.85),
    )
    row = await db_session.get(TenantRuleBookConfig, TESTING_TENANT_UUID)
    assert row is not None
    row.config = {
        **row.config,
        "document_types": [
            dt01.model_dump(by_alias=True),
            custom_dt.model_dump(by_alias=True),
        ],
    }
    await db_session.flush()
    clear_posting_config_cache()

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Supplier",
            document_type_code="DT-01",
            invoice_no="INV-CUSTOM-DT-COL",
            invoice_date=date(2026, 8, 11),
            status=InvoiceStatus.PROCESSED,
            file_hash="bundle-custom-dt-col",
        )
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-08-01&date_to=2026-08-31"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    assert "Freight note" in header
    bundle_row = next(
        r
        for r in data
        if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-CUSTOM-DT-COL"
    )
    assert bundle_row[header.index("Freight note")] == ""


@pytest.mark.asyncio
async def test_documents_bundle_export_includes_exception_anchor_with_po_sibling(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        document_type_code="DT-02",
        po_reference="PO-EXC-BUNDLE",
        invoice_no="PO-EXC-BUNDLE",
        invoice_date=date(2026, 9, 5),
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.PROCESSED,
        file_hash="bundle-exc-po-sibling",
    )
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        document_type_code="DT-01",
        po_reference="PO-EXC-BUNDLE",
        invoice_no="INV-EXC-BUNDLE",
        invoice_date=date(2026, 9, 10),
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        status=InvoiceStatus.EXCEPTION,
        file_hash="bundle-exc-anchor",
    )
    db_session.add_all([po_doc, anchor])
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-09-01&date_to=2026-09-30"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    assert "Status" in header
    row = next(
        r for r in data if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "INV-EXC-BUNDLE"
    )
    assert row[header.index("Status")] == "exception"
    po_col = header.index("PO (supporting)")
    assert_csv_hyperlink(row[po_col], url=vault_view_path(po_doc.id))


@pytest.mark.asyncio
async def test_documents_bundle_export_excludes_pending_anchor(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Supplier",
                document_type_code="DT-01",
                invoice_no="INV-PENDING-BUNDLE",
                invoice_date=date(2026, 9, 12),
                status=InvoiceStatus.PENDING,
                file_hash="bundle-pending-anchor",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Supplier",
                document_type_code="DT-01",
                invoice_no="INV-PARSING-BUNDLE",
                invoice_date=date(2026, 9, 13),
                status=InvoiceStatus.PARSING,
                file_hash="bundle-parsing-anchor",
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/api/reports/documents-bundle/export"
        "?date_from=2026-09-01&date_to=2026-09-30"
    )
    assert res.status_code == 200
    header, data = _read_csv(res.text)
    invoice_nos = _invoice_nos_from_rows(header, data)
    assert "INV-PENDING-BUNDLE" not in invoice_nos
    assert "INV-PARSING-BUNDLE" not in invoice_nos


@pytest.mark.asyncio
async def test_documents_bundle_export_status_column(
    db_session: AsyncSession,
) -> None:
    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.VALIDATING,
        document_type_code="DT-01",
        invoice_no="SHARED-VAL-88",
        invoice_date=date(2026, 9, 20),
        file_hash="bundle-validating-anchor",
    )
    sibling = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-06",
        invoice_no="SHARED-VAL-88",
        invoice_date=date(2026, 9, 20),
        file_hash="bundle-validating-sibling",
    )
    db_session.add_all([anchor, sibling])
    await db_session.commit()

    payload = await build_documents_bundle_export(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    header, data = _read_csv(payload.csv_text)
    row = next(
        r
        for r in data
        if _invoice_no_from_cell(r[header.index("Invoice no.")]) == "SHARED-VAL-88"
        and r[header.index("Status")] == "validating"
    )
    assert row[header.index("Status")] == "validating"
    assert row[header.index("Universal match")] == "Yes"
