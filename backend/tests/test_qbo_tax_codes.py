"""QuickBooks tax-code pull into Settings → Tax rates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sqlalchemy import select

from app.integrations.qbo.tax_codes import list_synced_tax_codes, sync_tax_codes_from_qbo
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.qbo_tax_code import QboTaxCode
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
async def test_sync_tax_codes_persists_purchase_and_sales_codes(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()

    calls = {"n": 0}

    async def _get(url, *args, **kwargs):
        calls["n"] += 1
        payload = (
            {
                "QueryResponse": {
                    "TaxRate": [
                        {"Id": "20", "Name": "GST", "RateValue": "10"},
                    ]
                }
            }
            if calls["n"] == 1
            else {
                "QueryResponse": {
                    "TaxCode": [
                        {
                            "Id": "11",
                            "Name": "GST on Purchases",
                            "Active": True,
                            "Taxable": True,
                            "PurchaseTaxRateList": {
                                "TaxRateDetail": [
                                    {"TaxRateRef": {"value": "20", "name": "GST"}},
                                ]
                            },
                        },
                        {
                            "Id": "2",
                            "Name": "GST on Sales",
                            "Active": True,
                            "SalesTaxRateList": {
                                "TaxRateDetail": [
                                    {"TaxRateRef": {"value": "20"}},
                                ]
                            },
                        },
                    ]
                }
            }
        )
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

    counters = await sync_tax_codes_from_qbo(db_session, TESTING_TENANT_UUID)
    assert counters.fetched == 2
    assert counters.created == 2

    entries = await list_synced_tax_codes(db_session, TESTING_TENANT_UUID, "934145000")
    by_id = {row.id: row for row in entries}
    assert by_id["11"].display_name == "GST on Purchases"
    assert by_id["11"].tax_type == "PURCHASES"
    assert by_id["11"].total_rate == 10
    assert by_id["11"].can_edit is False
    assert by_id["11"].source == "quickbooks_online"
    assert by_id["2"].tax_type == "SALES"
    row = (
        await db_session.execute(select(QboTaxCode).where(QboTaxCode.qbo_tax_code_id == "11"))
    ).scalar_one()
    assert row.purchase_rate is not None
    assert float(row.purchase_rate) == 10
