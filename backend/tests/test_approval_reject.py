"""Tests for reject workflow and blob relocation."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from tests.approval_test_helpers import patch_approval_file_checks
from app.services.vault.vault_paths import build_rejected_blob_name
from app.tenant_ids import TESTING_TENANT_UUID

_TID = TESTING_TENANT_UUID
_TENANT_PREFIX = f"tenants/{_TID}"


def test_build_rejected_blob_name() -> None:
    path = build_rejected_blob_name(
        _TID,
        "hv-org",
        tenant_name="High Volt Analytics",
        vendor_name="Atlassian Pty Ltd",
        storage_vendor_slug="atlassian",
        invoice_id=7,
        invoice_no="INV-007",
        invoice_date=date(2026, 5, 12),
        original_filename="scan.pdf",
    )
    from app.services.tenant.tenant_storage_paths import tenant_root

    assert path == (
        f"{tenant_root(_TID)}/rejected/Unrouted/Atlassian Pty Ltd/2026/May/INV-007_2026-05-12_id7.pdf"
    )


@pytest.mark.asyncio
async def test_reject_moves_file_and_sets_status(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Unrouted" / "Bad Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-001_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Bad Co",
        invoice_no="INV-001",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="exreject1",
        raw_file_path=str(pdf),
        total=Decimal("100"),
        validation_results=json.dumps(
            [{"rule": "VR12", "passed": False, "message": "fail", "skipped": False}]
        ),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "rejected"
    assert "rejected" in body["raw_file_path"].replace("\\", "/")
    assert "rejected/Unrouted/Bad Co/2026/May" in body["raw_file_path"].replace("\\", "/")
    assert not pdf.is_file()

    rejected_pdf = (
        upload_dir
        / _TENANT_PREFIX
        / "rejected"
        / "Unrouted"
        / "Bad Co"
        / "2026"
        / "May"
        / "INV-001_2026-05-04_id1.pdf"
    )
    assert rejected_pdf.is_file()

    listed = await client.get("/api/approvals")
    assert any(row["id"] == inv.id for row in listed.json()["data"])


@pytest.mark.asyncio
async def test_reject_processed_clears_journal_entries(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Posted Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-004_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Posted Co",
        invoice_no="INV-004",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="proc2",
        raw_file_path=str(pdf),
        total=Decimal("300"),
        account_code="6100",
        account_name="Software Expenses",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 5, 4),
            account_code="6100",
            account_name="Software Expenses",
            debit=Decimal("300"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "rejected"
    assert body["account_code"] is None

    journals = (
        await db_session.execute(
            select(JournalEntry).where(JournalEntry.invoice_id == inv.id)
        )
    ).scalars().all()
    assert journals == []


@pytest.mark.asyncio
async def test_reject_processed_invoice(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Done Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-003_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Done Co",
        invoice_no="INV-003",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="proc1",
        raw_file_path=str(pdf),
        total=Decimal("200"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "rejected"
    assert not pdf.is_file()


@pytest.mark.asyncio
async def test_reject_skips_relocate_when_file_already_in_rejected(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Vault" / "DT-03" / "Done Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-171_2026-05-04_id171.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Done Co",
        invoice_no="INV-171",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="rej-skip-1",
        raw_file_path=str(pdf),
        total=Decimal("200"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "rejected"
    assert pdf.is_file()


@pytest.mark.asyncio
async def test_approvals_board_returns_queue_pipeline_and_processed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    exception = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Queue Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="board-exc",
    )
    pending = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Pipeline Co",
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="board-pending",
    )
    processed = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Done Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="board-done",
        total=Decimal("10"),
    )
    db_session.add_all([exception, pending, processed])
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    rows = {row["id"]: row for row in res.json()["data"]}
    assert exception.id in rows
    assert pending.id in rows
    assert processed.id in rows
    assert rows[exception.id]["approval_board_column"] == "review"
    assert rows[pending.id]["approval_board_column"] == "processing"
    assert rows[processed.id]["approval_board_column"] == "approved"


@pytest.mark.asyncio
async def test_reject_requires_rejectable_status(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    pdf = tmp_path / "pending.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Pending Co",
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="pend1",
        raw_file_path=str(pdf),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_approve_from_rejected_restores_vault_path(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_approval_file_checks(monkeypatch)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "Unrouted" / "Bad Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-002_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Bad Co",
        invoice_no="INV-002",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="exrestore1",
        storage_vendor_slug="bad-co",
        raw_file_path=str(pdf),
        total=Decimal("50"),
        due_date=date(2026, 6, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "pending"
    assert "invoice" in body["raw_file_path"].replace("\\", "/")
    assert "Unrouted/Bad Co/2026/May" in body["raw_file_path"].replace("\\", "/")
    assert not pdf.is_file()

    vault_pdf = (
        upload_dir
        / _TENANT_PREFIX
        / "invoice"
        / "Unrouted"
        / "Bad Co"
        / "2026"
        / "May"
        / "INV-002_2026-05-04_id1.pdf"
    )
    assert vault_pdf.is_file()


@pytest.mark.asyncio
async def test_permanently_delete_rejected_invoice(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Gone Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-099_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Gone Co",
        invoice_no="INV-099",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="perm-del-1",
        raw_file_path=str(pdf),
        total=Decimal("99"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{inv.id}")
    assert res.status_code == 204
    assert not pdf.is_file()

    listed = await client.get("/api/approvals")
    assert all(row["id"] != inv.id for row in listed.json()["data"])

    get_res = await client.get(f"/api/invoices/{inv.id}")
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_permanent_delete_rejects_non_rejected_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Active Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="perm-del-exc",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{inv.id}")
    assert res.status_code == 400
    assert "Reject the document first" in res.json()["detail"]


@pytest.mark.asyncio
async def test_permanent_delete_processed_with_rejected_blob(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / _TENANT_PREFIX / "rejected" / "HvOrg" / "Orphan Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-orph_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Orphan Co",
        invoice_no="INV-orph",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="orph-1",
        raw_file_path=str(pdf),
        total=Decimal("50"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{inv.id}")
    assert res.status_code == 204
    assert not pdf.is_file()
