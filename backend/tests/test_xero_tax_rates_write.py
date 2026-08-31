"""Xero tax rate sync / create / delete for Settings."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.xero.tax_rates import is_system_tax_type
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.xero_connection import XeroConnection
from app.models.xero_tax_rate import SOURCE_SYSTEM_XERO, XeroTaxRate
from app.services.shared.token_vault import encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _xero_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XERO_ENABLED", "true")
    monkeypatch.setenv("XERO_CLIENT_ID", "xero-client")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "xero-secret")
    monkeypatch.setenv(
        "XERO_REDIRECT_URI",
        "http://localhost:8001/api/integrations/xero/callback",
    )
    monkeypatch.setenv(
        "XERO_SCOPES",
        "openid profile email offline_access accounting.settings accounting.contacts accounting.invoices",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed_connected(db_session: AsyncSession) -> AccountingIntegration:
    integration = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id="org-1",
        display_name="Demo Org",
        access_token_encrypted=encrypt_secret("access"),
        refresh_token_encrypted=encrypt_secret("refresh"),
    )
    db_session.add(integration)
    await db_session.flush()
    db_session.add(
        XeroConnection(
            accounting_integration_id=integration.id,
            tenant_id=TESTING_TENANT_UUID,
            xero_connection_id="conn-1",
            xero_tenant_id="org-1",
            xero_tenant_type="ORGANISATION",
            xero_tenant_name="Demo Org",
            active=True,
            selected=True,
        )
    )
    await db_session.flush()
    return integration


def test_system_tax_types_are_undeletable() -> None:
    assert is_system_tax_type("OUTPUT")
    assert is_system_tax_type("INPUT")
    assert is_system_tax_type("BASEXCLUDED")
    assert not is_system_tax_type("TAX001")
    assert not is_system_tax_type("TAX014")


@pytest.mark.asyncio
async def test_get_tax_rates_from_xero_cache(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    integration = await _seed_connected(db_session)
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-1",
            tax_type="OUTPUT",
            name="GST on Income",
            status="ACTIVE",
            effective_rate=10,
            display_tax_rate=10,
            source_system=SOURCE_SYSTEM_XERO,
            sync_status="active",
            raw_payload_json=(
                '{"TaxType":"OUTPUT","Name":"GST on Income","Status":"ACTIVE",'
                '"ReportTaxType":"OUTPUT","EffectiveRate":10,'
                '"TaxComponents":[{"Name":"GST","Rate":10.0}]}'
            ),
        )
    )
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-1",
            tax_type="TAX001",
            name="Custom 5%",
            status="ACTIVE",
            effective_rate=5,
            source_system=SOURCE_SYSTEM_XERO,
            sync_status="active",
            raw_payload_json=(
                '{"TaxType":"TAX001","Name":"Custom 5%","Status":"ACTIVE",'
                '"ReportTaxType":"INPUT","EffectiveRate":5,'
                '"TaxComponents":[{"Name":"GST","Rate":5.0}]}'
            ),
        )
    )
    await db_session.flush()

    res = await client.get("/api/tenants/current/tax-rates")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["xero_connected"] is True
    by_id = {row["id"]: row for row in body["tax_rates"]}
    assert by_id["OUTPUT"]["can_delete"] is False
    assert by_id["OUTPUT"]["can_edit"] is False
    assert by_id["OUTPUT"]["display_name"] == "GST on Income"
    assert by_id["OUTPUT"]["tax_type"] == "SALES"
    assert by_id["TAX001"]["can_delete"] is True
    assert by_id["TAX001"]["can_edit"] is True
    assert by_id["TAX001"]["tax_type"] == "PURCHASES"


@pytest.mark.asyncio
async def test_sync_tax_rates_pulls_from_xero(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_connected(db_session)
    mock_client = MagicMock()
    mock_client.get_json = AsyncMock(
        return_value={
            "TaxRates": [
                {
                    "TaxType": "INPUT",
                    "Name": "GST on Expenses",
                    "Status": "ACTIVE",
                    "ReportTaxType": "INPUT",
                    "EffectiveRate": 10,
                    "DisplayTaxRate": 10,
                    "TaxComponents": [{"Name": "GST", "Rate": 10}],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.integrations.xero.tax_rates.XeroApiClient",
        lambda **kwargs: mock_client,
    )

    res = await client.post("/api/tenants/current/tax-rates/sync")
    assert res.status_code == 200, res.text
    rows = res.json()["data"]["tax_rates"]
    assert len(rows) == 1
    assert rows[0]["id"] == "INPUT"
    assert rows[0]["can_delete"] is False
    mock_client.get_json.assert_awaited_once_with("TaxRates")


@pytest.mark.asyncio
async def test_create_tax_rate_writes_xero(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_connected(db_session)
    mock_client = MagicMock()
    mock_client.put_json = AsyncMock(
        return_value={
            "TaxRates": [
                {
                    "TaxType": "TAX002",
                    "Name": "Workshop GST",
                    "Status": "ACTIVE",
                    "ReportTaxType": "INPUT",
                    "EffectiveRate": 10,
                    "TaxComponents": [{"Name": "GST", "Rate": 10}],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.integrations.xero.tax_rates.XeroApiClient",
        lambda **kwargs: mock_client,
    )

    res = await client.post(
        "/api/tenants/current/tax-rates",
        json={
            "display_name": "Workshop GST",
            "tax_type": "PURCHASES",
            "components": [{"name": "GST", "rate": 10}],
        },
    )
    assert res.status_code == 200, res.text
    mock_client.put_json.assert_awaited_once()
    sent = mock_client.put_json.await_args.kwargs["json_body"]
    assert sent["TaxRates"][0]["Name"] == "Workshop GST"
    assert sent["TaxRates"][0]["ReportTaxType"] == "INPUT"
    created = next(row for row in res.json()["data"]["tax_rates"] if row["id"] == "TAX002")
    assert created["can_delete"] is True


@pytest.mark.asyncio
async def test_delete_system_tax_rate_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _seed_connected(db_session)
    res = await client.delete("/api/tenants/current/tax-rates/OUTPUT")
    assert res.status_code == 400, res.text
    assert "cannot be deleted" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_custom_tax_rate_writes_xero(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration = await _seed_connected(db_session)
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-1",
            tax_type="TAX003",
            name="Temp rate",
            status="ACTIVE",
            source_system=SOURCE_SYSTEM_XERO,
            sync_status="active",
        )
    )
    await db_session.flush()
    mock_client = MagicMock()
    mock_client.put_json = AsyncMock(return_value={"TaxRates": []})
    monkeypatch.setattr(
        "app.integrations.xero.tax_rates.XeroApiClient",
        lambda **kwargs: mock_client,
    )

    res = await client.delete("/api/tenants/current/tax-rates/TAX003")
    assert res.status_code == 200, res.text
    sent = mock_client.put_json.await_args.kwargs["json_body"]
    assert sent["TaxRates"][0] == {"TaxType": "TAX003", "Status": "DELETED"}
    ids = {row["id"] for row in res.json()["data"]["tax_rates"]}
    assert "TAX003" not in ids


@pytest.mark.asyncio
async def test_update_custom_tax_rate_writes_xero(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration = await _seed_connected(db_session)
    db_session.add(
        XeroTaxRate(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-1",
            tax_type="TAX004",
            name="Old name",
            status="ACTIVE",
            source_system=SOURCE_SYSTEM_XERO,
            sync_status="active",
        )
    )
    await db_session.flush()
    mock_client = MagicMock()
    mock_client.put_json = AsyncMock(
        return_value={
            "TaxRates": [
                {
                    "TaxType": "TAX004",
                    "Name": "New name",
                    "Status": "ACTIVE",
                    "ReportTaxType": "INPUT",
                    "EffectiveRate": 5,
                    "TaxComponents": [{"Name": "GST", "Rate": 5}],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.integrations.xero.tax_rates.XeroApiClient",
        lambda **kwargs: mock_client,
    )

    res = await client.put(
        "/api/tenants/current/tax-rates/TAX004",
        json={
            "display_name": "New name",
            "tax_type": "PURCHASES",
            "components": [{"name": "GST", "rate": 5}],
        },
    )
    assert res.status_code == 200, res.text
    mock_client.put_json.assert_awaited()
    updated = next(row for row in res.json()["data"]["tax_rates"] if row["id"] == "TAX004")
    assert updated["display_name"] == "New name"
    assert updated["can_edit"] is True
