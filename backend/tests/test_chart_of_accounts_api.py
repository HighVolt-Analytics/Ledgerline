"""Chart of accounts API — tenant-scoped persistence via rule book config + RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book.account_mapper import resolve_category_for_config
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.schemas.rule_book_config import ChartOfAccountEntry, validate_rule_book_config_payload
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_chart_of_accounts_with_sub_ledgers(client: AsyncClient, db_session: AsyncSession) -> None:
    payload = {
        "accounts": [
            {
                "code": "6110",
                "name": "Cloud Hosting Expense",
                "type": "Expense",
                "sub_ledgers": [
                    {"code": "01", "name": "AWS Production"},
                    {"code": "02", "name": "Azure Staging"},
                ],
            },
            {"code": "2000", "name": "Accounts Payable", "type": "Liability"},
        ]
    }

    patch_res = await client.patch("/api/tenants/current/chart-of-accounts", json=payload)
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()["data"]["accounts"]
    assert len(patched) == 2
    assert patched[0]["sub_ledgers"] == payload["accounts"][0]["sub_ledgers"]

    get_res = await client.get("/api/tenants/current/chart-of-accounts")
    assert get_res.status_code == 200, get_res.text
    loaded = get_res.json()["data"]["accounts"]
    assert loaded[0]["sub_ledgers"] == payload["accounts"][0]["sub_ledgers"]


@pytest.mark.asyncio
async def test_chart_of_accounts_rejects_duplicate_sub_ledger_codes(
    client: AsyncClient,
) -> None:
    payload = {
        "accounts": [
            {
                "code": "6110",
                "name": "Cloud Hosting Expense",
                "type": "Expense",
                "sub_ledgers": [
                    {"code": "01", "name": "AWS Production"},
                    {"code": "01", "name": "Azure Staging"},
                ],
            },
        ]
    }

    patch_res = await client.patch("/api/tenants/current/chart-of-accounts", json=payload)
    assert patch_res.status_code == 422, patch_res.text


def test_sub_ledger_helpers() -> None:
    from app.services.master_data.chart_of_accounts_service import (
        ledger_has_sub_ledger_catalog,
        sub_ledger_exists,
        sub_ledgers_for_ledger,
    )

    accounts = [
        ChartOfAccountEntry(
            code="6110",
            name="Cloud Hosting Expense",
            type="Expense",
            sub_ledgers=[
                {"code": "01", "name": "AWS Production"},
                {"code": "02", "name": "Azure Staging"},
            ],
        ),
        ChartOfAccountEntry(code="6120", name="Software Subscription Expense", type="Expense"),
    ]

    assert ledger_has_sub_ledger_catalog("Cloud Hosting Expense", accounts)
    assert not ledger_has_sub_ledger_catalog("Software Subscription Expense", accounts)
    assert sub_ledger_exists("Cloud Hosting Expense", "AWS Production", accounts)
    assert not sub_ledger_exists("Cloud Hosting Expense", "Unknown", accounts)
    assert len(sub_ledgers_for_ledger("cloud hosting expense", accounts)) == 2


def test_sub_ledger_valid_for_post_to() -> None:
    from app.services.classification.document_type_post_to_service import sub_ledger_valid_for_post_to

    accounts = [
        ChartOfAccountEntry(
            code="6110",
            name="Cloud Hosting Expense",
            type="Expense",
            sub_ledgers=[{"code": "01", "name": "AWS Production"}],
        ),
    ]

    assert sub_ledger_valid_for_post_to("Cloud Hosting Expense", "", accounts)
    assert sub_ledger_valid_for_post_to("Cloud Hosting Expense", "AWS Production", accounts)
    assert not sub_ledger_valid_for_post_to("Cloud Hosting Expense", "Legacy Free Text", accounts)
    assert sub_ledger_valid_for_post_to("Unknown Ledger", "Legacy Free Text", accounts)


@pytest.mark.asyncio
async def test_chart_of_accounts_round_trip(client: AsyncClient, db_session: AsyncSession) -> None:
    payload = {
        "accounts": [
            {"code": "6110", "name": "Cloud Hosting Expense", "type": "Expense"},
            {"code": "1400", "name": "GST Paid", "type": "Asset"},
            {"code": "2000", "name": "Accounts Payable", "type": "Liability"},
            {"code": "9999", "name": "Suspense Account", "type": "Liability"},
        ]
    }

    patch_res = await client.patch("/api/tenants/current/chart-of-accounts", json=payload)
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()["data"]["accounts"]
    assert len(patched) == 4
    assert patched[0]["code"] == "6110"

    get_res = await client.get("/api/tenants/current/chart-of-accounts")
    assert get_res.status_code == 200, get_res.text
    loaded = get_res.json()["data"]["accounts"]
    assert loaded == patched

    stored = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    stored_coa = stored.get("chart_of_accounts") or []
    assert len(stored_coa) == len(payload["accounts"])
    for stored_row, expected_row in zip(stored_coa, payload["accounts"], strict=True):
        assert stored_row["code"] == expected_row["code"]
        assert stored_row["name"] == expected_row["name"]
        assert stored_row["type"] == expected_row["type"]
        assert stored_row.get("sub_ledgers", []) == expected_row.get("sub_ledgers", [])


def test_resolve_category_uses_tenant_chart_of_accounts() -> None:
    config = validate_rule_book_config_payload(
        {
            "chart_of_accounts": [
                {"code": "7777", "name": "Custom Expense", "type": "Expense"},
            ]
        }
    )
    mapping = resolve_category_for_config("Custom Expense", config)
    assert mapping.account_code == "7777"
    assert mapping.account_name == "Custom Expense"

    missing = resolve_category_for_config("Unknown Ledger", config)
    assert missing.account_code == "9999"


def test_resolve_category_without_tenant_coa_uses_suspense() -> None:
    config = validate_rule_book_config_payload({})
    assert config.chart_of_accounts == []
    mapping = resolve_category_for_config("Cloud Hosting Expense", config)
    assert mapping.account_code == "9999"
    assert mapping.account_name == "Cloud Hosting Expense"
