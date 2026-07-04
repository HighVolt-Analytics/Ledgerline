"""Chart of accounts API — tenant-scoped persistence via rule book config + RLS."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rule_book.account_mapper import resolve_category_for_config
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.tenant_ids import TESTING_TENANT_UUID


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
    assert stored.get("chart_of_accounts") == payload["accounts"]


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
