"""Phase 4 master data APIs."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.employee_master import EmployeeMasterRecord
from app.schemas.master_data import EmployeeMasterCreate
from app.services.audit.audit_service import json_safe_audit_detail
from app.services.master_data.master_data_service import create_employee_master
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
from app.tenant_ids import TESTING_TENANT_UUID


def test_json_safe_audit_detail_serializes_datetime() -> None:
    sent = datetime(2026, 8, 26, 2, 30, tzinfo=timezone.utc)
    out = json_safe_audit_detail(
        {
            "before": {"confirmation_sent_at": sent, "name": "vishnu"},
        }
    )
    assert out is not None
    assert str(out["before"]["confirmation_sent_at"]).startswith("2026-08-26T02:30:00")
    assert out["before"]["name"] == "vishnu"


@pytest.mark.asyncio
async def test_vendor_master_crud(client: AsyncClient, db_session: AsyncSession) -> None:
    clear_classification_config_cache()

    res = await client.get("/api/vendor-masters")
    assert res.status_code == 200
    initial = res.json()["data"]
    assert isinstance(initial, list)
    initial_count = len(initial)

    res = await client.post(
        "/api/vendor-masters",
        json={
            "name": "Test Vendor Pty Ltd",
            "abn": "51824753556",
            "status": "Active",
            "default_ledger": "Office",
        },
    )
    assert res.status_code == 201
    created = res.json()["data"]
    master_id = created["id"]
    assert created["name"] == "Test Vendor Pty Ltd"
    assert created["db_id"] > 0

    res = await client.patch(
        f"/api/vendor-masters/{master_id}",
        json={"payment_terms": "Net 30"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["payment_terms"] == "Net 30"

    res = await client.get("/api/vendor-masters")
    assert len(res.json()["data"]) == initial_count + 1

    res = await client.get("/api/rule-book/config")
    assert res.status_code == 200
    names = [v["name"] for v in res.json()["data"]["vendor_masters"]]
    assert "Test Vendor Pty Ltd" in names

    res = await client.delete(f"/api/vendor-masters/{master_id}")
    assert res.status_code == 204

    events = (
        await db_session.execute(
            select(AuditLog.event).where(
                AuditLog.event.in_(("vendor_master_created", "vendor_master_updated"))
            )
        )
    ).scalars().all()
    assert "vendor_master_created" in events
    assert "vendor_master_updated" in events


@pytest.mark.asyncio
async def test_vendor_master_normalizes_formatted_abn(client: AsyncClient) -> None:
    clear_classification_config_cache()

    res = await client.post(
        "/api/vendor-masters",
        json={
            "name": "Sysco Foods Australia Pty Ltd",
            "abn": "51 824 753 556",
            "status": "Active",
        },
    )
    assert res.status_code == 201
    master_id = res.json()["data"]["id"]
    assert res.json()["data"]["abn"] == "51824753556"

    res = await client.patch(
        f"/api/vendor-masters/{master_id}",
        json={"abn": "51 824 753 556"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["abn"] == "51824753556"

    await client.delete(f"/api/vendor-masters/{master_id}")


@pytest.mark.asyncio
async def test_employee_master_crud(client: AsyncClient) -> None:
    res = await client.post(
        "/api/employee-masters",
        json={
            "name": "Alex Chen",
            "email": "alex@example.com",
            "whatsapp_number": "+61400000000",
            "status": "Active",
            "budget": {"monthly": 500, "quarterly": 1200, "annual": 4500, "categories": []},
        },
    )
    assert res.status_code == 201
    created = res.json()["data"]
    master_id = created["id"]

    res = await client.patch(
        f"/api/employee-masters/{master_id}",
        json={"role": "Engineer"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["role"] == "Engineer"

    res = await client.get("/api/rule-book/config")
    ids = [e["id"] for e in res.json()["data"]["employee_masters"]]
    assert master_id in ids

    res = await client.delete(f"/api/employee-masters/{master_id}")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_employee_master_patch_with_confirmation_timestamps(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(name="Jordan Lee", email="jordan@example.com"),
    )
    row = (
        await db_session.execute(
            select(EmployeeMasterRecord).where(EmployeeMasterRecord.master_id == created.id)
        )
    ).scalar_one()
    now = datetime.now(timezone.utc)
    row.confirmation_sent_at = now
    row.confirmed_at = now
    await db_session.commit()

    res = await client.patch(
        f"/api/employee-masters/{created.id}",
        json={"last_claim": "2026-08-01"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["last_claim"] == "2026-08-01"

    await client.delete(f"/api/employee-masters/{created.id}")


@pytest.mark.asyncio
async def test_pending_vendor_promote(client: AsyncClient) -> None:
    res = await client.post(
        "/api/pending-vendors",
        json={
            "detected_name": "Mystery Supplies",
            "detected_abn": "51824753556",
            "confidence": 42,
        },
    )
    assert res.status_code == 201
    pending_id = res.json()["data"]["id"]

    res = await client.get("/api/pending-vendors")
    assert any(row["id"] == pending_id for row in res.json()["data"])

    res = await client.post(
        f"/api/pending-vendors/{pending_id}/promote",
        json={"name": "Mystery Supplies Pty Ltd", "status": "Active", "default_ledger": "Office"},
    )
    assert res.status_code == 200
    vendor_id = res.json()["data"]["id"]

    res = await client.get("/api/pending-vendors")
    assert not any(row["id"] == pending_id for row in res.json()["data"])

    res = await client.get(f"/api/vendor-masters")
    assert any(v["id"] == vendor_id for v in res.json()["data"])

    res = await client.delete(f"/api/vendor-masters/{vendor_id}")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_pending_vendor_promote_syncs_capture_registry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.invoice import Invoice, InvoiceStatus
    from app.models.vendor import VendorRegistry
    from sqlalchemy import select

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Registry Sync Co",
        email_sender="invoices@registrysync.test",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="promo-reg-sync",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(
        "/api/pending-vendors",
        json={
            "detected_name": "Registry Sync Co",
            "confidence": 30,
            "source_invoice_id": inv.id,
        },
    )
    assert res.status_code == 201
    pending_id = res.json()["data"]["id"]

    res = await client.post(
        f"/api/pending-vendors/{pending_id}/promote",
        json={"name": "Registry Sync Co", "status": "Active", "default_ledger": "Office"},
    )
    assert res.status_code == 200
    vendor_id = res.json()["data"]["id"]

    row = (
        await db_session.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == TESTING_TENANT_UUID,
                VendorRegistry.vendor_slug == "registry-sync-co",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.sender_pattern == "invoices@registrysync.test"

    await client.delete(f"/api/vendor-masters/{vendor_id}")


@pytest.mark.asyncio
async def test_rule_book_put_ignores_embedded_masters(client: AsyncClient) -> None:
    res = await client.get("/api/rule-book/config")
    body = res.json()["data"]
    vendor_count = len(body["vendor_masters"])
    body["vendor_masters"] = [{"id": "fake", "name": "Should Not Persist"}]
    body["employee_masters"] = [{"id": "fake-em", "name": "Ghost"}]

    res = await client.put("/api/rule-book/config", json=body)
    assert res.status_code == 200
    saved = res.json()["data"]
    assert len(saved["vendor_masters"]) == vendor_count
    assert all(v["name"] != "Should Not Persist" for v in saved["vendor_masters"])
    assert all(e["name"] != "Ghost" for e in saved["employee_masters"])
