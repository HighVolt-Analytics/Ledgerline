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
from app.services.vault_paths import build_rejected_blob_name


def test_build_rejected_blob_name() -> None:
    path = build_rejected_blob_name(
        "hv-org",
        org_name="High Volt Analytics",
        vendor_name="Atlassian Pty Ltd",
        storage_vendor_slug="atlassian",
        invoice_id=7,
        invoice_no="INV-007",
        invoice_date=date(2026, 5, 12),
        original_filename="scan.pdf",
    )
    assert path == "rejected/HvOrg/Atlassian Pty Ltd/2026/May/INV-007_2026-05-12.pdf"


@pytest.mark.asyncio
async def test_reject_moves_file_and_sets_status(
    client: AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Bad Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-001_2026-05-04.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        org_id=1,
        vendor="Bad Co",
        invoice_no="INV-001",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="exreject1",
        raw_file_path=str(pdf),
        total=Decimal("100"),
        validation_results=json.dumps(
            [{"rule": "VR05", "passed": False, "message": "fail", "skipped": False}]
        ),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "rejected"
    assert "rejected" in body["raw_file_path"].replace("\\", "/")
    assert "HvOrg/Bad Co/2026/May" in body["raw_file_path"].replace("\\", "/")
    assert not pdf.is_file()

    rejected_pdf = upload_dir / "rejected" / "HvOrg" / "Bad Co" / "2026" / "May" / "INV-001_2026-05-04.pdf"
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
    pdf = vault_path / "INV-004_2026-05-04.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        org_id=1,
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
    pdf = vault_path / "INV-003_2026-05-04.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        org_id=1,
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
        org_id=1,
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
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = upload_dir / "rejected" / "HvOrg" / "Bad Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-002_2026-05-04.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        org_id=1,
        vendor="Bad Co",
        invoice_no="INV-002",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="exrestore1",
        storage_vendor_slug="bad-co",
        raw_file_path=str(pdf),
        total=Decimal("50"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "pending"
    assert "invoice" in body["raw_file_path"].replace("\\", "/")
    assert "HvOrg/Bad Co/2026/May" in body["raw_file_path"].replace("\\", "/")
    assert not pdf.is_file()

    vault_pdf = upload_dir / "invoice" / "HvOrg" / "Bad Co" / "2026" / "May" / "INV-002_2026-05-04.pdf"
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

    rejected_path = upload_dir / "rejected" / "HvOrg" / "Gone Co" / "2026" / "May"
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-099_2026-05-04.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        org_id=1,
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
        org_id=1,
        vendor="Active Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="perm-del-exc",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.delete(f"/api/approvals/{inv.id}")
    assert res.status_code == 400
