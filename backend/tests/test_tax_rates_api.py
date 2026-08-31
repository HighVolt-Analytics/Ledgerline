"""Tenant tax rates API — persisted in rule book config + RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.tenant_ids import TESTING_TENANT_UUID


def _gst_on_expenses() -> dict:
    return {
        "display_name": "GST on Expenses",
        "tax_type": "PURCHASES",
        "components": [{"name": "GST", "rate": 10}],
    }


@pytest.mark.asyncio
async def test_tax_rates_round_trip(client: AsyncClient) -> None:
    payload = {"tax_rates": [_gst_on_expenses()]}
    patch_res = await client.patch("/api/tenants/current/tax-rates", json=payload)
    assert patch_res.status_code == 200, patch_res.text
    saved = patch_res.json()["data"]["tax_rates"]
    assert len(saved) == 1
    assert saved[0]["display_name"] == "GST on Expenses"
    assert saved[0]["tax_type"] == "PURCHASES"
    assert saved[0]["components"] == [{"name": "GST", "rate": 10.0}]
    assert saved[0]["total_rate"] == 10.0
    assert saved[0]["id"]
    assert patch_res.json()["data"]["source"] == "none"
    assert patch_res.json()["data"]["xero_connected"] is False
    assert patch_res.json()["data"]["provider"] is None

    get_res = await client.get("/api/tenants/current/tax-rates")
    assert get_res.status_code == 200, get_res.text
    loaded = get_res.json()["data"]["tax_rates"]
    assert loaded[0]["display_name"] == "GST on Expenses"
    assert loaded[0]["id"] == saved[0]["id"]


@pytest.mark.asyncio
async def test_tax_rates_reject_duplicate_names(client: AsyncClient) -> None:
    payload = {
        "tax_rates": [
            _gst_on_expenses(),
            {
                "display_name": "gst on expenses",
                "tax_type": "SALES",
                "components": [{"name": "GST", "rate": 10}],
            },
        ]
    }
    patch_res = await client.patch("/api/tenants/current/tax-rates", json=payload)
    assert patch_res.status_code == 422, patch_res.text


@pytest.mark.asyncio
async def test_tax_rates_reject_invalid_type_and_empty_components(client: AsyncClient) -> None:
    bad_type = await client.patch(
        "/api/tenants/current/tax-rates",
        json={
            "tax_rates": [
                {
                    "display_name": "Custom",
                    "tax_type": "NOT_A_TYPE",
                    "components": [{"name": "GST", "rate": 10}],
                }
            ]
        },
    )
    assert bad_type.status_code == 422, bad_type.text

    empty = await client.patch(
        "/api/tenants/current/tax-rates",
        json={
            "tax_rates": [
                {"display_name": "Custom", "tax_type": "SALES", "components": []}
            ]
        },
    )
    assert empty.status_code == 422, empty.text

    too_long = await client.patch(
        "/api/tenants/current/tax-rates",
        json={
            "tax_rates": [
                {
                    "display_name": "x" * 51,
                    "tax_type": "SALES",
                    "components": [{"name": "GST", "rate": 10}],
                }
            ]
        },
    )
    assert too_long.status_code == 422, too_long.text


@pytest.mark.asyncio
async def test_tax_rates_survive_chart_of_accounts_save(client: AsyncClient) -> None:
    tax_res = await client.patch(
        "/api/tenants/current/tax-rates",
        json={"tax_rates": [_gst_on_expenses()]},
    )
    assert tax_res.status_code == 200, tax_res.text

    coa_res = await client.patch(
        "/api/tenants/current/chart-of-accounts",
        json={
            "accounts": [
                {"code": "6110", "name": "Cloud Hosting Expense", "type": "Expense"},
                {"code": "2000", "name": "Accounts Payable", "type": "Liability"},
            ]
        },
    )
    assert coa_res.status_code == 200, coa_res.text

    get_res = await client.get("/api/tenants/current/tax-rates")
    assert get_res.status_code == 200, get_res.text
    names = [row["display_name"] for row in get_res.json()["data"]["tax_rates"]]
    assert names == ["GST on Expenses"]


@pytest.mark.asyncio
async def test_tax_rates_survive_rule_book_slice_merge(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from app.services.rule_book.rule_book_config_io import merge_persisted_rule_book_slices

    tax_res = await client.patch(
        "/api/tenants/current/tax-rates",
        json={"tax_rates": [_gst_on_expenses()]},
    )
    assert tax_res.status_code == 200, tax_res.text

    merged = await merge_persisted_rule_book_slices(
        db_session,
        TESTING_TENANT_UUID,
        {"schema_version": 1, "document_types": []},
    )
    names = [row["display_name"] for row in merged.get("tax_rates") or []]
    assert names == ["GST on Expenses"]

    stored = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    stored_names = [row["display_name"] for row in stored.get("tax_rates") or []]
    assert stored_names == ["GST on Expenses"]
