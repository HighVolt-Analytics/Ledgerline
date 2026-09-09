"""QuickBooks chart-of-accounts pull including subaccounts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sqlalchemy import select

from app.integrations.qbo.accounts import (
    children_of,
    is_top_level_qbo_account,
    list_active_qbo_accounts,
    local_code_for_qbo,
    sub_ledgers_from_children,
    sync_accounts_from_qbo,
)
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.qbo_account import QboAccount
from app.services.shared.token_vault import encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID


def _connected_qbo() -> AccountingIntegration:
    return AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id="934145000",
        display_name="Sandbox Co",
        access_token_encrypted=encrypt_secret("qbo-access"),
        refresh_token_encrypted=encrypt_secret("qbo-refresh"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )


@pytest.mark.asyncio
async def test_sync_accounts_nests_subaccounts(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _get(url, *args, **kwargs):
        payload = {
            "QueryResponse": {
                "Account": [
                    {
                        "Id": "80",
                        "Name": "Office Expenses",
                        "AcctNum": "6100",
                        "AccountType": "Expense",
                        "AccountSubType": "OfficeGeneralAdministrativeExpenses",
                        "Classification": "Expense",
                        "Active": True,
                        "SubAccount": False,
                    },
                    {
                        "Id": "81",
                        "Name": "Software",
                        "AcctNum": "6101",
                        "AccountType": "Expense",
                        "Classification": "Expense",
                        "Active": True,
                        "SubAccount": True,
                        "ParentRef": {"value": "80", "name": "Office Expenses"},
                    },
                ]
            }
        }
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        response.content = b"{}"
        return response

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.integrations.qbo.client.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    counters = await sync_accounts_from_qbo(db_session, TESTING_TENANT_UUID)
    assert counters.fetched == 2
    rows = await list_active_qbo_accounts(db_session, TESTING_TENANT_UUID, "934145000")
    parent = next(row for row in rows if row.qbo_account_id == "80")
    assert is_top_level_qbo_account(parent)
    assert local_code_for_qbo(parent) == "6100"
    kids = children_of("80", rows)
    assert [local_code_for_qbo(row) for row in kids] == ["6101"]
    subs = sub_ledgers_from_children(kids)
    assert subs[0].name == "Software"
    stored = (
        await db_session.execute(select(QboAccount).where(QboAccount.qbo_account_id == "81"))
    ).scalar_one()
    assert stored.parent_ref == "80"
    assert stored.sub_account is True


def test_find_reusable_qbo_account_matches_name_even_when_code_is_new() -> None:
    from types import SimpleNamespace

    from app.integrations.qbo.accounts import find_reusable_qbo_account

    parent = SimpleNamespace(
        qbo_account_id="80",
        name="Office Expenses",
        acct_num="6100",
        fully_qualified_name="Office Expenses",
        parent_ref=None,
        sub_account=False,
        active=True,
    )
    child = SimpleNamespace(
        qbo_account_id="81",
        name="Software",
        acct_num="6101",
        fully_qualified_name="Office Expenses:Software",
        parent_ref="80",
        sub_account=True,
        active=True,
    )
    reuse, conflict = find_reusable_qbo_account(
        [parent, child],
        name="Office Expenses",
        code="9999",
    )
    assert reuse is parent
    assert conflict is None

    reuse, conflict = find_reusable_qbo_account(
        [parent, child],
        name="Software",
        code="8888",
    )
    assert reuse is None
    assert conflict is child

    reuse, conflict = find_reusable_qbo_account(
        [parent, child],
        name="Software",
        code="8888",
        parent_id="80",
    )
    assert reuse is child
