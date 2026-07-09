"""APIs added for Ledgerline-style frontend integration."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor import VendorRegistry
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
from tests.approval_test_helpers import patch_approval_file_checks
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_list_tenants(client: AsyncClient) -> None:
    res = await client.get("/api/tenants")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["is_current"] is True
    assert "name" in rows[0]
    assert "slug" in rows[0]
    assert rows[0]["currency"] == "AUD"


@pytest.mark.asyncio
async def test_get_settings(client: AsyncClient) -> None:
    res = await client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()["data"]
    assert "graph_mailbox" in data
    assert "blob_enabled" in data
    assert "abn_validation_mode" in data
    assert "azure_client_secret" not in data


@pytest.mark.asyncio
async def test_rule_book_config_get_put_roundtrip(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_classification_config_cache()

    res = await client.get("/api/rule-book/config")
    assert res.status_code == 200
    original = res.json()["data"]

    updated = {
        **original,
        "posting_defaults": {
            **original.get("posting_defaults", {}),
            "fallback_account": "Suspense Account",
        },
    }
    res = await client.put("/api/rule-book/config", json=updated)
    assert res.status_code == 200

    res = await client.get("/api/rule-book/config")
    assert res.json()["data"]["posting_defaults"]["fallback_account"] == "Suspense Account"

    get_settings.cache_clear()
    clear_rule_book_cache()
    clear_classification_config_cache()


@pytest.mark.asyncio
async def test_rule_book_config_put_invalid_email_rule(client: AsyncClient) -> None:
    res = await client.get("/api/rule-book/config")
    body = res.json()["data"]
    body["email_capture_rules"] = [{"id": "bad", "name": "Bad rule"}]
    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_document_matrix(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Acme Pty Ltd",
            invoice_date=date(2026, 5, 13),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="matrix-test",
        )
    )
    await db_session.flush()

    res = await client.get("/api/matrix?page=1&page_size=100")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) >= 1
    stages = rows[0]["stages"]
    assert len(stages) == 6
    assert stages[0]["stage"] == "Received"
    assert stages[0]["state"] in ("done", "pending", "fail", "skipped")
    assert rows[0]["flag"] == "Clean"
    assert rows[0]["payment_status"] in ("—", "Awaiting Payment", "On Hold", "Paid")


@pytest.mark.asyncio
async def test_document_matrix_flags_exception(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Risky Vendor",
            status=InvoiceStatus.EXCEPTION,
            evaluation_status="needs_review",
            currency="AUD",
            file_hash="matrix-exc",
        )
    )
    await db_session.flush()

    res = await client.get("/api/matrix?page=1&page_size=100")
    assert res.status_code == 200
    row = next(r for r in res.json()["data"] if r["invoice"]["vendor"] == "Risky Vendor")
    assert row["flag"] == "Anomaly Detected"
    assert row["payment_status"] == "On Hold"


@pytest.mark.asyncio
async def test_list_invoices_vendor_and_date_filters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(tenant_id=TESTING_TENANT_UUID,
                vendor="Qantas Airways Limited",
                invoice_date=date(2026, 5, 13),
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="f1",
            ),
            Invoice(tenant_id=TESTING_TENANT_UUID,
                vendor="Hilton Sydney",
                invoice_date=date(2026, 6, 1),
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="f2",
            ),
        ]
    )
    await db_session.flush()

    res = await client.get("/api/invoices?vendor=Qantas")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1
    assert "Qantas" in res.json()["data"][0]["vendor"]

    res = await client.get(
        "/api/invoices?invoice_date_from=2026-05-01&invoice_date_to=2026-05-31"
    )
    assert len(res.json()["data"]) == 1


@pytest.mark.asyncio
async def test_list_invoices_connected_mailbox_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mb_a = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="inbox-a@example.com",
        display_name="Inbox A",
        is_active=True,
    )
    mb_b = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="inbox-b@example.com",
        display_name="Inbox B",
        is_active=True,
    )
    db_session.add_all([mb_a, mb_b])
    await db_session.flush()

    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Vendor A",
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="mb-a",
                connected_mailbox_id=mb_a.id,
                email_sender="vendor@example.com",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Vendor B",
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="mb-b",
                connected_mailbox_id=mb_b.id,
                email_sender="other@example.com",
            ),
        ]
    )
    await db_session.flush()

    res = await client.get(f"/api/invoices?connected_mailbox_id={mb_a.id}")
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["connected_mailbox_id"] == mb_a.id
    assert body["data"][0]["email_sender"] == "vendor@example.com"


@pytest.mark.asyncio
async def test_toggle_mailbox_active_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mb = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="toggle@example.com",
        display_name="Toggle Test",
        is_active=True,
    )
    db_session.add(mb)
    await db_session.flush()

    res = await client.patch(f"/api/mailboxes/{mb.id}/toggle")
    assert res.status_code == 200
    assert res.json()["data"]["is_active"] is False

    res = await client.patch(f"/api/mailboxes/{mb.id}/toggle")
    assert res.status_code == 200
    assert res.json()["data"]["is_active"] is True

    res = await client.get("/api/mailboxes")
    assert res.json()["data"][0]["is_active"] is True


@pytest.mark.asyncio
async def test_delete_mailbox_with_linked_invoices(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    mb = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="remove@example.com",
        display_name="Remove Me",
        is_active=True,
    )
    db_session.add(mb)
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        vendor="Vendor Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="mb-delete-1",
        email_sender="remove@example.com",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.delete(f"/api/mailboxes/{mb.id}")
    assert res.status_code == 204

    listed = await client.get("/api/mailboxes")
    assert listed.json()["data"] == []

    inv_res = await client.get(f"/api/invoices/{inv.id}")
    assert inv_res.status_code == 200
    assert inv_res.json()["data"]["connected_mailbox_id"] is None


@pytest.mark.asyncio
async def test_download_invoice_file_local(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    pdf = upload_dir / "test_inv.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="abc",
        raw_file_path=str(pdf),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get(f"/api/invoices/{inv.id}/file")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert b"%PDF" in res.content


@pytest.mark.asyncio
async def test_delete_vendor(client: AsyncClient, db_session: AsyncSession) -> None:
    row = VendorRegistry(tenant_id=TESTING_TENANT_UUID,
        vendor_slug="test-vendor",
        vendor_name="Test Vendor",
        sender_pattern="@test.com",
        approved=False,
    )
    db_session.add(row)
    await db_session.flush()

    res = await client.delete(f"/api/vendors/{row.id}")
    assert res.status_code == 204

    res = await client.get("/api/vendors")
    ids = [v["id"] for v in res.json()["data"]]
    assert row.id not in ids


@pytest.mark.asyncio
async def test_approvals_list_and_approve(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_approval_file_checks(monkeypatch)
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Bad Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="ex1",
        raw_file_path=str(pdf),
        due_date=date(2026, 7, 1),
        validation_results=json.dumps(
            [{"rule": "VR12", "passed": False, "message": "fail", "skipped": False}]
        ),
        total=Decimal("100"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/approvals")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "pending"

    res = await client.get("/api/approvals")
    assert len(res.json()["data"]) == 0


@pytest.mark.asyncio
async def test_approve_requires_stored_file(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _noop_repair(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(
        "app.services.approval_service.repair_invoice_stored_path",
        _noop_repair,
    )
    monkeypatch.setattr(
        "app.services.approval_service.stored_file_available",
        lambda *_args, **_kwargs: False,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="No File Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="nofile1",
        raw_file_path=None,
        total=Decimal("50"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 400
    assert "no stored file" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_attach_then_approve(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Attach Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="old",
        total=Decimal("50"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(
        f"/api/invoices/{inv.id}/attach",
        files={"file": ("invoice.pdf", b"%PDF-1.4 attach", "application/pdf")},
    )
    assert res.status_code == 200
    assert res.json()["data"]["has_stored_file"] is True

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "pending"


@pytest.mark.asyncio
async def test_approve_rejects_processed(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="ok1",
        raw_file_path="/tmp/x.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 400
