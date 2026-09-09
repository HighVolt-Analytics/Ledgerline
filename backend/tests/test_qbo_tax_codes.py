"""QuickBooks tax-code pull into Settings → Tax rates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
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


def _tax_row(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        active=kwargs.get("active", True),
        sync_status=kwargs.get("sync_status", "active"),
        purchase_rate=kwargs.get("purchase_rate"),
        name=kwargs.get("name"),
        qbo_tax_code_id=kwargs.get("qbo_tax_code_id", "11"),
    )


def test_invoice_gst_percent_uses_rate_then_zero_amount() -> None:
    from app.integrations.qbo.tax_codes import invoice_gst_percent

    assert invoice_gst_percent(SimpleNamespace(gst_rate=Decimal("20"), gst=Decimal("10"))) == Decimal(
        "20.00"
    )
    assert invoice_gst_percent(SimpleNamespace(gst_rate=None, gst=Decimal("0"))) == Decimal("0.00")
    assert invoice_gst_percent(SimpleNamespace(gst_rate=None, gst=Decimal("15"))) is None


def test_default_purchase_tax_code_name() -> None:
    from app.integrations.qbo.tax_codes import default_purchase_tax_code_name

    assert default_purchase_tax_code_name(Decimal("20")) == "GST 20%"
    assert default_purchase_tax_code_name(Decimal("0")) == "GST free 0%"
    assert default_purchase_tax_code_name(Decimal("10.50")) == "GST 10.5%"


def test_match_purchase_tax_code_prefers_gst_purchase_and_never_renames() -> None:
    from app.integrations.qbo.tax_codes import match_purchase_tax_code

    rows = [
        _tax_row(qbo_tax_code_id="1", name="Other 10", purchase_rate=Decimal("10")),
        _tax_row(qbo_tax_code_id="11", name="GST on Purchases", purchase_rate=Decimal("10")),
        _tax_row(qbo_tax_code_id="2", name="GST on Sales", purchase_rate=None),
    ]
    hit = match_purchase_tax_code(rows, Decimal("10"))
    assert hit is not None
    assert hit.qbo_tax_code_id == "11"
    assert match_purchase_tax_code(rows, Decimal("20")) is None


@pytest.mark.asyncio
async def test_ensure_invoice_tax_reuses_then_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.qbo.tax_codes import ensure_invoice_qbo_tax_code

    existing = _tax_row(qbo_tax_code_id="11", name="GST on Purchases", purchase_rate=Decimal("10"))
    created = _tax_row(qbo_tax_code_id="99", name="GST 20%", purchase_rate=Decimal("20"))
    monkeypatch.setattr(
        "app.integrations.qbo.tax_codes.require_qbo_ready",
        AsyncMock(return_value=(MagicMock(), "934145000")),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.tax_codes._list_cached_tax_codes",
        AsyncMock(return_value=[existing]),
    )
    create = AsyncMock(return_value=created)
    monkeypatch.setattr("app.integrations.qbo.tax_codes.create_tax_code_in_qbo", create)

    reused = await ensure_invoice_qbo_tax_code(
        AsyncMock(),
        SimpleNamespace(id=1, tenant_id=TESTING_TENANT_UUID, gst_rate=Decimal("10")),
    )
    assert reused is not None
    assert reused["created"] is False
    assert reused["tax_code_id"] == "11"
    create.assert_not_awaited()

    made = await ensure_invoice_qbo_tax_code(
        AsyncMock(),
        SimpleNamespace(id=2, tenant_id=TESTING_TENANT_UUID, gst_rate=Decimal("20")),
    )
    assert made is not None
    assert made["created"] is True
    assert made["name"] == "GST 20%"
    create.assert_awaited_once()
    assert create.await_args.kwargs["display_name"] == "GST 20%"
    assert create.await_args.kwargs["report_type"] == "PURCHASES"

