from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.xero.client import XeroApiError
from app.integrations.xero.currencies import ensure_xero_currency
from app.models.xero_currency import XeroCurrency
from app.tenant_ids import TESTING_TENANT_UUID
from tests.test_xero_export_pipeline import _seed_xero_ready


@pytest.mark.asyncio
async def test_ensure_currency_noop_when_already_local(db_session, monkeypatch):
    await _seed_xero_ready(db_session)
    client = MagicMock()
    client.get_currencies = AsyncMock()
    client.put_json = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.xero.currencies.XeroApiClient", lambda **kwargs: client
    )
    row = await ensure_xero_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="aud")
    assert row is not None
    assert row.code == "AUD"
    client.get_currencies.assert_not_called()
    client.put_json.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_currency_persists_from_live_list(db_session, monkeypatch):
    await _seed_xero_ready(db_session)
    client = MagicMock()
    client.get_currencies = AsyncMock(
        return_value=[{"Code": "USD", "Description": "United States Dollar"}]
    )
    client.put_json = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.xero.currencies.XeroApiClient", lambda **kwargs: client
    )
    row = await ensure_xero_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="USD")
    assert row is not None
    assert row.code == "USD"
    client.put_json.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_currency_puts_when_missing_on_xero(db_session, monkeypatch):
    await _seed_xero_ready(db_session)
    client = MagicMock()
    client.get_currencies = AsyncMock(return_value=[{"Code": "AUD"}])
    client.put_json = AsyncMock(return_value={"Currencies": [{"Code": "USD"}]})
    monkeypatch.setattr(
        "app.integrations.xero.currencies.XeroApiClient", lambda **kwargs: client
    )
    row = await ensure_xero_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="USD")
    assert row is not None
    assert row.code == "USD"
    client.put_json.assert_awaited_once_with("Currencies", json_body={"Code": "USD"})


@pytest.mark.asyncio
async def test_ensure_currency_returns_none_when_org_cannot_add(db_session, monkeypatch):
    await _seed_xero_ready(db_session)
    client = MagicMock()
    client.get_currencies = AsyncMock(return_value=[{"Code": "AUD"}])
    client.put_json = AsyncMock(
        side_effect=XeroApiError(400, "The organisation does not have a subscription")
    )
    monkeypatch.setattr(
        "app.integrations.xero.currencies.XeroApiClient", lambda **kwargs: client
    )
    row = await ensure_xero_currency(db_session, tenant_id=TESTING_TENANT_UUID, code="USD")
    assert row is None
