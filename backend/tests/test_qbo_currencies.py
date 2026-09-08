"""Ensure QuickBooks company currencies exist (home, list, or POST)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.integrations.qbo.client import QboApiError
from app.integrations.qbo.currencies import (
    QboCurrencyWriteError,
    ensure_qbo_currency,
    sync_currencies_from_qbo,
)
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.qbo_currency import QboCurrency
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


def _client(monkeypatch: pytest.MonkeyPatch, *, query, post=None) -> MagicMock:
    client = MagicMock()
    client.query = AsyncMock(side_effect=query)
    client.post_entity = AsyncMock(side_effect=post) if post is not None else AsyncMock()
    monkeypatch.setattr(
        "app.integrations.qbo.currencies.QboApiClient",
        lambda **kwargs: client,
    )
    return client


def _prefs(*, home: str = "AUD", multicurrency: bool = False) -> dict:
    return {
        "QueryResponse": {
            "Preferences": [
                {
                    "CurrencyPrefs": {
                        "HomeCurrency": {"value": home},
                        "MultiCurrencyEnabled": multicurrency,
                    }
                }
            ]
        }
    }


def _company_currencies(*codes: str) -> dict:
    return {
        "QueryResponse": {
            "CompanyCurrency": [{"Code": code, "Name": code, "Active": True} for code in codes]
        }
    }


@pytest.mark.asyncio
async def test_ensure_home_currency_without_post(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()
    client = _client(
        monkeypatch,
        query=lambda statement: _prefs(home="AUD", multicurrency=False),
    )
    row = await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="aud")
    assert row.code == "AUD"
    client.post_entity.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_uses_existing_company_currency_list(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _query(statement: str):
        if "Preferences" in statement:
            return _prefs(home="AUD", multicurrency=True)
        return _company_currencies("AUD", "USD")

    client = _client(monkeypatch, query=_query)
    row = await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="USD")
    assert row.code == "USD"
    client.post_entity.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_posts_when_multicurrency_on_and_code_missing(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _query(statement: str):
        if "Preferences" in statement:
            return _prefs(home="AUD", multicurrency=True)
        return _company_currencies("AUD")

    client = _client(
        monkeypatch,
        query=_query,
        post=lambda entity, body: {"CompanyCurrency": {"Code": body["Code"], "Active": True}},
    )
    row = await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="EUR")
    assert row.code == "EUR"
    client.post_entity.assert_awaited_once_with("companycurrency", {"Code": "EUR"})


@pytest.mark.asyncio
async def test_ensure_blocks_foreign_when_multicurrency_off(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _query(statement: str):
        if "Preferences" in statement:
            return _prefs(home="AUD", multicurrency=False)
        return _company_currencies("AUD")

    client = _client(monkeypatch, query=_query)
    with pytest.raises(QboCurrencyWriteError) as exc:
        await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="EUR")
    assert exc.value.status_code == 409
    assert "Multicurrency" in exc.value.message
    client.post_entity.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_noop_when_already_local(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    integration = _connected_qbo()
    db_session.add(integration)
    await db_session.flush()
    db_session.add(
        QboCurrency(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            realm_id="934145000",
            code="USD",
            name="USD",
            active=True,
            sync_status="active",
        )
    )
    await db_session.flush()
    client = _client(monkeypatch, query=AsyncMock())
    row = await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="usd")
    assert row.code == "USD"
    client.query.assert_not_called()
    client.post_entity.assert_not_called()


@pytest.mark.asyncio
async def test_sync_persists_home_and_listed_currencies(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _query(statement: str):
        if "Preferences" in statement:
            return _prefs(home="AUD", multicurrency=True)
        return _company_currencies("USD")

    _client(monkeypatch, query=_query)
    counters = await sync_currencies_from_qbo(db_session, TESTING_TENANT_UUID)
    assert counters.created == 2
    codes = {
        row.code
        for row in (
            await db_session.execute(
                select(QboCurrency).where(QboCurrency.tenant_id == TESTING_TENANT_UUID)
            )
        ).scalars()
    }
    assert codes == {"AUD", "USD"}


@pytest.mark.asyncio
async def test_ensure_surfaces_qbo_post_error(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    async def _query(statement: str):
        if "Preferences" in statement:
            return _prefs(home="AUD", multicurrency=True)
        return _company_currencies("AUD")

    _client(
        monkeypatch,
        query=_query,
        post=AsyncMock(side_effect=QboApiError(400, "Invalid currency")),
    )
    with pytest.raises(QboCurrencyWriteError) as exc:
        await ensure_qbo_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="ZZZ")
    assert "Invalid currency" in exc.value.message
