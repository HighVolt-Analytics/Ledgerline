"""Phase 4 master data APIs."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book_mapper import clear_classification_config_cache


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
