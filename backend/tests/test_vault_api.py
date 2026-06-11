"""HTTP tests for vault API."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.services.invoice_evaluation_service import ROUTE_PURCHASE


@pytest.mark.asyncio
async def test_vault_tree_empty(client: AsyncClient) -> None:
    res = await client.get("/api/vault/tree")
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["tree"] == []
    assert body["data"]["files"] == []
    assert "blob_enabled" in body["data"]


@pytest.mark.asyncio
async def test_vault_tree_uses_hv_org_folder(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    org = await db_session.get(Organisation, 1)
    assert org is not None
    org.slug = "hv-org"
    org.name = "High Volt Analytics"
    await db_session.flush()

    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    db_session.add(
        Invoice(
            org_id=1,
            vendor="Atlassian Pty Ltd",
            invoice_no="INV-001",
            invoice_date=date(2026, 5, 4),
            total=Decimal("100.00"),
            status=InvoiceStatus.PROCESSED,
            raw_file_path=str(pdf_path),
            file_hash="abc123def456",
            route_target=ROUTE_PURCHASE,
        )
    )
    await db_session.flush()

    res = await client.get("/api/vault/tree")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["tree"][0]["label"] == "HvOrg"
    assert data["files"][0]["virtual_path"].startswith("invoice/HvOrg/Purchase Management/")


@pytest.mark.asyncio
async def test_vault_tree_with_stored_file(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    db_session.add(
        Invoice(
            org_id=1,
            vendor="Atlassian Pty Ltd",
            invoice_no="INV-001",
            invoice_date=date(2026, 5, 4),
            total=Decimal("100.00"),
            status=InvoiceStatus.PROCESSED,
            raw_file_path=str(pdf_path),
            file_hash="abc123def456",
            storage_vendor_slug="atlassian",
            route_target=ROUTE_PURCHASE,
        )
    )
    await db_session.flush()

    res = await client.get("/api/vault/tree")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data["files"]) == 1
    file_entry = data["files"][0]
    assert file_entry["invoice_id"] == 1
    assert file_entry["book"] == "Purchase Management"
    assert file_entry["vendor"] == "Atlassian Pty Ltd"
    assert file_entry["year"] == "2026"
    assert file_entry["month"] == "May"
    assert file_entry["has_stored_file"] is True
    assert file_entry["virtual_path"].startswith("invoice/")
    assert len(data["tree"]) == 1
    assert data["tree"][0]["kind"] == "org"
    assert data["tree"][0]["label"] == "HvOrg"
    assert data["tree"][0]["count"] == 1
    assert data["tree"][0]["children"][0]["kind"] == "book"


@pytest.mark.asyncio
async def test_vault_tree_excludes_no_file_path(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            org_id=1,
            vendor="Demo Vendor",
            status=InvoiceStatus.PROCESSED,
            total=Decimal("50.00"),
        )
    )
    await db_session.flush()

    res = await client.get("/api/vault/tree")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["files"] == []
    assert data["tree"] == []


@pytest.mark.asyncio
async def test_vault_tree_excludes_duplicate_skipped(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    pdf_path = tmp_path / "dup.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    db_session.add(
        Invoice(
            org_id=1,
            vendor="Dup Vendor",
            status=InvoiceStatus.DUPLICATE_SKIPPED,
            raw_file_path=str(pdf_path),
            file_hash="duphash123456",
        )
    )
    await db_session.flush()

    res = await client.get("/api/vault/tree")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["files"] == []


@pytest.mark.asyncio
async def test_vault_migrate_blob_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.vault_service.blob_storage.is_blob_enabled",
        lambda: False,
    )
    res = await client.post("/api/vault/migrate")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["moved"] == 0
    assert data["skipped"] == 0
    assert data["blob_enabled"] is False
