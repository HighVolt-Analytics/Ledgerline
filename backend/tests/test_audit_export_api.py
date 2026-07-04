
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Audit log CSV export."""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.services.audit.audit_export_service import (
    PurchaseVaultLinks,
    audit_rows_to_csv,
    dedupe_high_churn_audit_rows,
    excel_hyperlink,
    excel_hyperlinks_joined,
    fetch_linked_docs_for_invoices,
    flatten_audit_detail,
    format_audit_timestamp,
    format_linked_docs_export,
    purchase_vault_links_for_po,
    vault_view_path,
)
from app.services.shared.public_app_url import resolve_public_app_base_url
from app.services.audit.audit_change_summary import summarize_audit_change
from app.services.audit.audit_detail_helpers import truncate_audit_error


def assert_csv_hyperlink(cell: str, *, url: str, label: str | None = None) -> None:
    assert cell.startswith("=HYPERLINK("), cell
    assert url in cell
    if label is not None:
        assert label in cell


def test_excel_hyperlink_wraps_url_with_label() -> None:
    cell = excel_hyperlink("https://app.example/vault?invoice=9", "Open invoice")
    assert_csv_hyperlink(cell, url="https://app.example/vault?invoice=9", label="Open invoice")


def test_excel_hyperlinks_joined_stacks_multiple_links() -> None:
    cell = excel_hyperlinks_joined(
        [
            ("https://app.example/vault?invoice=1", "DT-26:DOC-1"),
            ("https://app.example/vault?invoice=2", "DT-03:DOC-2"),
        ]
    )
    assert cell.startswith("=")
    assert "HYPERLINK(" in cell
    assert "CHAR(10)" in cell
    assert "DT-26:DOC-1" in cell
    assert "DT-03:DOC-2" in cell


def test_format_audit_timestamp_utc() -> None:
    dt = datetime(2026, 6, 10, 11, 38, 45, tzinfo=timezone.utc)
    assert format_audit_timestamp(dt) == "10 Jun 2026, 11:38 UTC"


def test_flatten_audit_detail_extracts_common_fields() -> None:
    flat = flatten_audit_detail(
        {
            "vendor": "Acme Pty Ltd",
            "po_number": "PO-1001",
            "amount": 1250.5,
            "vendor_confidence": 0.92,
            "account_name": "Software subscriptions",
            "rule_type": "expense_rule",
            "match_reason": "keyword: aws",
            "hold_reason": "Missing PO",
            "actor_name": "Jane Doe",
            "actor_email": "jane@example.com",
        }
    )
    assert flat["vendor_name"] == "Acme Pty Ltd"
    assert flat["po_number"] == "PO-1001"
    assert flat["amount"] == "1250.5"
    assert flat["confidence_score"] == "0.92"
    assert flat["ledger"] == "Software subscriptions"
    assert flat["rule_matched"] == "expense_rule: keyword: aws"
    assert flat["hold_reason"] == "Missing PO"
    assert flat["actor_name"] == "Jane Doe"
    assert flat["actor_email"] == "jane@example.com"


def test_audit_rows_to_csv_column_order_and_flattening() -> None:
    row = AuditLog(
        id=42,
        tenant_id=TESTING_TENANT_UUID,
        event="mapping_applied",
        invoice_id=7,
        correlation_id="corr-abc",
        created_at=datetime(2026, 6, 10, 11, 38, tzinfo=timezone.utc),
        detail={
            "vendor_name": "Telstra",
            "amount": 99,
            "account_name": "Telecom",
            "actor_name": "System",
            "actor_email": "system@org.test",
        },
    )
    reader = csv.reader(io.StringIO(audit_rows_to_csv([row])))
    header, data = next(reader), next(reader)
    assert header == [
        "id",
        "created_at",
        "event",
        "invoice_id",
        "vault_url",
        "po_vault_url",
        "grn_vault_url",
        "invoice_vault_url",
        "linked_docs",
        "invoice_no",
        "route_target",
        "document_status",
        "evaluation_status",
        "correlation_id",
        "vendor_name",
        "po_number",
        "amount",
        "confidence_score",
        "ledger",
        "rule_matched",
        "hold_reason",
        "actor_name",
        "actor_email",
        "change_summary",
    ]
    assert data[0] == "42"
    assert data[1] == "10 Jun 2026, 11:38 UTC"
    assert data[2] == "mapping_applied"
    assert data[3] == "7"
    assert_csv_hyperlink(data[4], url=vault_view_path(7), label="View in Vault")
    assert data[5] == ""
    assert data[6] == ""
    assert data[7] == ""
    assert data[8] == ""
    assert data[13] == "corr-abc"
    assert data[14] == "Telstra"
    assert data[16] == "99"
    assert data[18] == "Telecom"
    assert data[21] == "System"
    assert data[22] == "system@org.test"
    assert data[23] == "Mapped to Telecom"


def test_reconciliation_skipped_clears_hold_reason() -> None:
    detail = {"reason": "RC1: invoice totals 768.50 != AP credits 268.50"}
    flat = flatten_audit_detail(detail, event="reconciliation_skipped")
    assert flat["hold_reason"] == ""
    assert summarize_audit_change("reconciliation_skipped", detail) == detail["reason"]


def test_email_moved_clears_hold_reason() -> None:
    detail = {"folder": "Exceptions", "reason": "validation_failed", "outcome": "exception"}
    flat = flatten_audit_detail(detail, event="email_moved")
    assert flat["hold_reason"] == ""
    assert "validation_failed" in summarize_audit_change("email_moved", detail)


def test_purchase_sync_enriches_vendor_and_amount_from_invoice() -> None:
    invoice = Invoice(
        id=9,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia",
        total=Decimal("1420.00"),
    )
    row = AuditLog(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        event="purchase_invoice_document_synced",
        invoice_id=9,
        detail={"po_number": "PO-MKT-2026-014"},
    )
    flat = flatten_audit_detail(row.detail, event=row.event, invoice=invoice)
    assert flat["vendor_name"] == "Sysco Australia"
    assert flat["amount"] == "1420.00"
    assert flat["po_number"] == "PO-MKT-2026-014"

    purchase_links = PurchaseVaultLinks(
        po_vault_url=vault_view_path(10),
        grn_vault_url=vault_view_path(11),
        invoice_vault_url=vault_view_path(9),
    )
    csv_text = audit_rows_to_csv(
        [row],
        invoice_map={9: invoice},
        purchase_vault_by_po_id={1: purchase_links},
        purchase_vault_by_po_number={"PO-MKT-2026-014": purchase_links},
    )
    reader = csv.reader(io.StringIO(csv_text))
    next(reader)
    data = next(reader)
    assert_csv_hyperlink(data[5], url=vault_view_path(10), label="Open PO")
    assert_csv_hyperlink(data[6], url=vault_view_path(11), label="Open GRN")
    assert_csv_hyperlink(data[7], url=vault_view_path(9), label="Open invoice")
    assert data[8] == ""
    assert data[14] == "Sysco Australia"
    assert data[16] == "1420.00"
    assert data[23] == "PO-MKT-2026-014 invoice linked"


def test_vault_view_path_full_url_from_public_app_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")
    monkeypatch.setenv("AZURE_WEBAPP_URL", "")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.delenv("BASE_PATH", raising=False)
    get_settings.cache_clear()
    assert vault_view_path(40) == "http://localhost:5173/vault?invoice=40"
    assert vault_view_path(None) == ""
    get_settings.cache_clear()


def test_vault_view_path_staging_base_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_APP_URL", "https://staging.highvolt.tech/ledgerlink")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("BASE_PATH", "/ledgerlink")
    get_settings.cache_clear()
    assert vault_view_path(40) == "https://staging.highvolt.tech/ledgerlink/vault?invoice=40"
    get_settings.cache_clear()


def test_resolve_public_app_base_from_oauth_return_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    monkeypatch.setenv("AZURE_WEBAPP_URL", "")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.setenv(
        "GRAPH_OAUTH_FRONTEND_RETURN_URL",
        "http://localhost:5173/integrations",
    )
    get_settings.cache_clear()
    assert resolve_public_app_base_url() == "http://localhost:5173"
    get_settings.cache_clear()


def test_flatten_enriches_from_invoice() -> None:
    invoice = Invoice(
        id=35,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Telstra Corporation Limited",
        invoice_no="EXP-MKT-TEST-TEL-001",
        po_reference=None,
        total=Decimal("189.00"),
        route_target="Expenses Management",
        vendor_confidence=0.0,
        account_name="Software Subscription Expense",
        currency="AUD",
        file_hash="x",
    )
    flat = flatten_audit_detail(
        {"source": "azure_di", "confidence": "high"},
        event="parse_completed",
        invoice=invoice,
    )
    assert flat["invoice_no"] == "EXP-MKT-TEST-TEL-001"
    assert flat["route_target"] == "Expenses Management"
    assert flat["vendor_name"] == "Telstra Corporation Limited"
    assert flat["amount"] == "189.00"
    assert flat["rule_matched"] == "parser: azure_di"


def test_dedupe_high_churn_audit_rows_keeps_latest() -> None:
    older = AuditLog(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        event="purchase_invoice_document_synced",
        invoice_id=32,
        created_at=datetime(2026, 6, 10, 7, 40, tzinfo=timezone.utc),
    )
    newer = AuditLog(
        id=2,
        tenant_id=TESTING_TENANT_UUID,
        event="purchase_invoice_document_synced",
        invoice_id=32,
        created_at=datetime(2026, 6, 10, 11, 38, tzinfo=timezone.utc),
    )
    other = AuditLog(
        id=3,
        tenant_id=TESTING_TENANT_UUID,
        event="invoice_processed",
        invoice_id=32,
        created_at=datetime(2026, 6, 10, 11, 39, tzinfo=timezone.utc),
    )
    kept = dedupe_high_churn_audit_rows([newer, older, other])
    assert [row.id for row in kept] == [2, 3]


def test_flatten_prefers_point_in_time_status_from_detail() -> None:
    invoice = Invoice(
        id=10,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="ready_for_payment",
        route_target="Purchase Management",
    )
    flat = flatten_audit_detail(
        {
            "document_status": "mapping",
            "evaluation_status": "awaiting_po",
            "route_target": "Purchase Management",
        },
        event="validation_passed",
        invoice=invoice,
    )
    assert flat["document_status"] == "mapping"
    assert flat["evaluation_status"] == "awaiting_po"


def test_pipeline_error_truncates_xml_in_hold_reason_and_summary() -> None:
    xml_error = (
        '<?xml version="1.0"?><Error><Code>BlobNotFound</Code>'
        "<Message>The specified blob does not exist.</Message></Error>"
    )
    flat = flatten_audit_detail({"error": xml_error}, event="pipeline_error")
    assert "\n" not in flat["hold_reason"]
    assert len(flat["hold_reason"]) <= 200
    assert "BlobNotFound" in flat["hold_reason"] or "ErrorCode" in flat["hold_reason"]
    summary = summarize_audit_change("pipeline_error", {"error": xml_error})
    assert "\n" not in summary
    assert len(summary) <= 220


def test_truncate_audit_error_extracts_error_code() -> None:
    text = 'ErrorCode: AuthenticationFailed — server failed to authenticate'
    assert "AuthenticationFailed" in truncate_audit_error(text)


def test_dedupe_parse_completed_keeps_latest() -> None:
    older = AuditLog(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        event="parse_completed",
        invoice_id=5,
        created_at=datetime(2026, 6, 10, 7, 0, tzinfo=timezone.utc),
    )
    newer = AuditLog(
        id=2,
        tenant_id=TESTING_TENANT_UUID,
        event="parse_completed",
        invoice_id=5,
        created_at=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
    )
    kept = dedupe_high_churn_audit_rows([newer, older])
    assert [row.id for row in kept] == [2]


def test_purchase_vault_links_for_po_resolves_three_documents() -> None:
    po = PurchaseOrder(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-MKT-2026-014",
        po_document_id=10,
        invoice_id=30,
    )
    po.goods_receipts = [
        GoodsReceipt(
            purchase_order_id=1,
            grn_qty=Decimal("1"),
            grn_invoice_id=20,
        )
    ]
    links = purchase_vault_links_for_po(po)
    assert links.po_vault_url == vault_view_path(10)
    assert links.grn_vault_url == vault_view_path(20)
    assert links.invoice_vault_url == vault_view_path(30)


def test_three_way_match_csv_includes_all_vault_urls() -> None:
    row = AuditLog(
        id=5,
        tenant_id=TESTING_TENANT_UUID,
        event="three_way_match_evaluated",
        invoice_id=30,
        detail={
            "purchase_order_id": 1,
            "po_number": "PO-MKT-2026-014",
            "match_status": "3-Way Match",
            "status": "full_match",
        },
    )
    purchase_links = PurchaseVaultLinks(
        po_vault_url=vault_view_path(10),
        grn_vault_url=vault_view_path(20),
        invoice_vault_url=vault_view_path(30),
    )
    csv_text = audit_rows_to_csv(
        [row],
        purchase_vault_by_po_id={1: purchase_links},
    )
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    data = next(reader)
    assert header.index("po_vault_url") == 5
    assert header.index("linked_docs") == 8
    assert_csv_hyperlink(
        data[header.index("po_vault_url")],
        url=vault_view_path(10),
        label="Open PO",
    )
    assert_csv_hyperlink(
        data[header.index("grn_vault_url")],
        url=vault_view_path(20),
        label="Open GRN",
    )
    assert_csv_hyperlink(
        data[header.index("invoice_vault_url")],
        url=vault_view_path(30),
        label="Open invoice",
    )
    assert data[header.index("linked_docs")] == ""
    assert "PO-MKT-2026-014" in data[header.index("change_summary")]


def test_purchase_sync_summary_includes_match_status() -> None:
    summary = summarize_audit_change(
        "purchase_invoice_document_synced",
        {
            "po_number": "PO-MKT-2026-014",
            "match_status": "3-Way Match",
            "three_way_status": "full_match",
        },
    )
    assert "PO-MKT-2026-014" in summary
    assert "3-Way Match" in summary
    assert "full_match" in summary


def test_parse_completed_summary() -> None:
    summary = summarize_audit_change(
        "parse_completed",
        {"source": "azure_di", "confidence": "high", "text_length": 1200},
    )
    assert "azure_di" in summary
    assert "high confidence" in summary


@pytest.mark.asyncio
async def test_audit_export_csv(client: AsyncClient, db_session: AsyncSession) -> None:

    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="invoice_processed",
            invoice_id=None,
            detail={"actor_name": "Auditor"},
        )
    )
    await db_session.commit()

    res = await client.get("/api/audit-log/export?month=2026-06&document_only=false")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    body = res.text
    header = body.splitlines()[0]
    assert "vendor_name" in header
    assert "po_vault_url" in header
    assert "grn_vault_url" in header
    assert "invoice_vault_url" in header
    assert "linked_docs" in header
    assert header.endswith("change_summary")
    assert "invoice_processed" in body
    assert "Auditor" in body


@pytest.mark.asyncio
async def test_audit_export_linked_docs_column(db_session: AsyncSession) -> None:
    from app.services.dossier.dossier_linked_documents_service import build_dossier_linked_documents
    from tests.conftest import TESTING_TENANT_UUID

    anchor = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Importer",
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-01",
        invoice_no="260671582",
        file_hash="audit-export-anchor",
    )
    coo = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Carrier",
        status=InvoiceStatus.PROCESSED,
        document_type_code="DT-26",
        invoice_no="260671582",
        file_hash="audit-export-coo",
    )
    db_session.add_all([anchor, coo])
    await db_session.flush()

    linked = await build_dossier_linked_documents(
        db_session,
        anchor,
        definition=None,
        document_types=[],
    )
    export_value = format_linked_docs_export(anchor.id, linked)
    assert "DT-26" in export_value
    assert_csv_hyperlink(export_value, url=vault_view_path(coo.id), label="DT-26")

    linked_map = await fetch_linked_docs_for_invoices(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice_map={anchor.id: anchor},
    )
    assert linked_map[anchor.id] == export_value

    row = AuditLog(
        id=99,
        tenant_id=TESTING_TENANT_UUID,
        event="validation_passed",
        invoice_id=anchor.id,
    )
    csv_text = audit_rows_to_csv(
        [row],
        invoice_map={anchor.id: anchor},
        linked_docs_by_invoice=linked_map,
    )
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    data = next(reader)
    assert data[header.index("linked_docs")] == export_value
    assert_csv_hyperlink(data[header.index("linked_docs")], url=vault_view_path(coo.id))
