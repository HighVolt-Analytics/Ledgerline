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
    assert [
        {"code": row["code"], "name": row["name"]}
        for row in patched[0]["sub_ledgers"]
    ] == payload["accounts"][0]["sub_ledgers"]

    get_res = await client.get("/api/tenants/current/chart-of-accounts")
    assert get_res.status_code == 200, get_res.text
    loaded = get_res.json()["data"]["accounts"]
    assert [
        {"code": row["code"], "name": row["name"]}
        for row in loaded[0]["sub_ledgers"]
    ] == payload["accounts"][0]["sub_ledgers"]


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

    # Unmapped names fall back to THIS TENANT's own configured fallback
    # account looked up by name in their own chart -- never a hardcoded
    # global code. This tenant never configured "Suspense Account" in
    # their chart either, so it degrades to an empty code (caught by
    # get_unresolved_control_accounts() before anything posts).
    missing = resolve_category_for_config("Unknown Ledger", config)
    assert missing.account_code == ""
    assert missing.account_name == "Suspense Account"


def test_resolve_category_without_tenant_coa_uses_suspense() -> None:
    config = validate_rule_book_config_payload({})
    assert config.chart_of_accounts == []
    # No chart of accounts configured at all -- there is nowhere safe to
    # post, so this degrades to an empty account_code paired with the
    # tenant's configured fallback label ("Suspense Account" by default),
    # never a hardcoded numeric code that could collide with a real
    # account once the tenant does configure a chart.
    mapping = resolve_category_for_config("Cloud Hosting Expense", config)
    assert mapping.account_code == ""
    assert mapping.account_name == "Suspense Account"


def test_resolve_category_uses_tenant_own_fallback_when_configured() -> None:
    """When a tenant HAS a real Suspense/fallback account in their own chart,
    an unmapped category must resolve to that tenant's actual code -- proving
    the fallback path is tenant-scoped rather than a global constant.
    """
    config = validate_rule_book_config_payload(
        {
            "posting_defaults": {"fallback_account": "Unclassified Suspense"},
            "chart_of_accounts": [
                {"code": "7777", "name": "Custom Expense", "type": "Expense"},
                {"code": "4321", "name": "Unclassified Suspense", "type": "Liability"},
            ],
        }
    )
    mapping = resolve_category_for_config("Totally Unknown Category", config)
    assert mapping.account_code == "4321"
    assert mapping.account_name == "Unclassified Suspense"
    assert mapping.expense_category == "Totally Unknown Category"


def test_upsert_linked_replaces_old_code() -> None:
    from app.services.master_data.chart_of_accounts_service import _clip_entry, _upsert_linked

    entries = [
        _clip_entry(
            code="2000",
            name="Accounts Payable",
            ledger_type="Liability",
            sub_type="CURRLIAB",
            linked_providers=["xero"],
            sub_ledgers=[],
        ),
        _clip_entry(
            code="6110",
            name="Hosting",
            ledger_type="Expense",
            sub_type="EXPENSE",
            linked_providers=[],
            sub_ledgers=[],
        ),
    ]
    renamed = _clip_entry(
        code="2001",
        name="Trade Payables",
        ledger_type="Liability",
        sub_type="CURRLIAB",
        linked_providers=["xero"],
        sub_ledgers=[],
    )
    merged = _upsert_linked(entries, renamed, match_key="2000")
    codes = [item.code for item in merged]
    assert codes == ["2001", "6110"]


@pytest.mark.asyncio
async def test_connected_local_save_keeps_omitted_xero_codes(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.master_data import chart_of_accounts_service as svc

    seed = await client.patch(
        "/api/tenants/current/chart-of-accounts",
        json={
            "accounts": [
                {"code": "6110", "name": "Cloud Hosting Expense", "type": "Expense"},
                {"code": "2000", "name": "Accounts Payable", "type": "Liability", "linked_providers": ["xero"]},
            ]
        },
    )
    assert seed.status_code == 200, seed.text

    async def fake_conn(*_args, **_kwargs):
        return (object(), "xero-tenant")

    async def fake_list(*_args, **_kwargs):
        return [
            type(
                "Row",
                (),
                {
                    "xero_account_id": "xa-2000",
                    "code": "2000",
                    "name": "Accounts Payable",
                    "account_type": "CURRLIAB",
                    "account_class": "LIABILITY",
                    "status": "ACTIVE",
                    "raw_payload_json": "{}",
                },
            )()
        ]

    monkeypatch.setattr(svc, "_xero_connection", fake_conn)
    monkeypatch.setattr(svc, "list_active_xero_accounts", fake_list)

    patched = await client.patch(
        "/api/tenants/current/chart-of-accounts",
        json={"accounts": [{"code": "6110", "name": "Cloud Hosting Expense", "type": "Expense"}]},
    )
    assert patched.status_code == 200, patched.text
    codes = {row["code"] for row in patched.json()["data"]["accounts"]}
    assert codes == {"6110", "2000"}


@pytest.mark.asyncio
async def test_update_xero_account_renames_catalogue_code(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.chart_of_accounts import UpdateChartOfAccountsRequest, UpsertXeroChartOfAccountRequest
    from app.services.master_data import chart_of_accounts_service as svc
    from app.tenant_ids import TESTING_TENANT_UUID

    await svc.save_chart_of_accounts(
        db_session,
        TESTING_TENANT_UUID,
        UpdateChartOfAccountsRequest(
            accounts=[
                ChartOfAccountEntry(
                    code="2000",
                    name="Accounts Payable",
                    type="Liability",
                    linked_providers=["xero"],
                )
            ]
        ),
    )

    cached = type(
        "Row",
        (),
        {
            "code": "2000",
            "name": "Accounts Payable",
            "account_type": "CURRLIAB",
            "account_class": "LIABILITY",
            "raw_payload_json": "{}",
        },
    )()
    updated = type("Row", (), {"code": "2001", "name": "Trade Payables"})()

    async def fake_conn(*_args, **_kwargs):
        return (object(), "xero-tenant")

    async def fake_get(*_args, **_kwargs):
        return cached

    async def fake_update(*_args, **_kwargs):
        return updated

    monkeypatch.setattr(svc, "_xero_connection", fake_conn)
    monkeypatch.setattr(svc, "get_xero_account", fake_get)
    monkeypatch.setattr(svc, "is_system_xero_account", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(svc, "update_account_in_xero", fake_update)

    payload = await svc.update_xero_chart_of_account(
        db_session,
        TESTING_TENANT_UUID,
        "acct-1",
        UpsertXeroChartOfAccountRequest(
            code="2001",
            name="Trade Payables",
            type="Liability",
            sub_type="CURRLIAB",
            sub_ledgers=[],
        ),
    )
    codes = [row.code for row in payload.accounts]
    assert codes == ["2001"]
    assert payload.accounts[0].name == "Trade Payables"
