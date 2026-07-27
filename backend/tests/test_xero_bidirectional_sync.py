"""Tests for real Xero master-data persistence and sync counts."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, func

from app.config import get_settings
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.accounting_sync_job import AccountingSyncJob
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_connection import XeroConnection
from app.models.xero_tax_rate import XeroTaxRate
from app.models.xero_currency import XeroCurrency
from app.services.integration.xero_client import XeroApiError
from app.services.integration.xero_master_data_service import (
    get_master_data_totals,
    list_xero_accounts,
)
from app.services.integration.xero_sync_counts import EntitySyncCounters, payload_hash
from app.services.integration.xero_sync_service import (
    mark_sync_committed,
    sync_contacts,
    sync_settings,
)
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
        "openid profile email accounting.settings.read accounting.contacts accounting.transactions offline_access",
    )
    monkeypatch.setenv("XERO_WEBHOOK_KEY", "whsec_test_key")
    monkeypatch.setenv("XERO_API_BASE_URL", "https://api.xero.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed_connected(db_session) -> AccountingIntegration:
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


def _mock_xero_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accounts=None,
    tax=None,
    contacts=None,
    orgs=None,
    currencies=None,
    currencies_error: Exception | None = None,
):
    # Organisation payloads typically omit Currencies (staging root cause).
    default_orgs = orgs or [
        {
            "OrganisationID": "org-1",
            "Name": "Demo Org",
            "BaseCurrency": "AUD",
            "CountryCode": "AU",
        }
    ]
    currency_rows = (
        currencies
        if currencies is not None
        else [{"Code": "AUD", "Description": "Australian Dollar"}]
    )
    client = MagicMock()
    client.get_json = AsyncMock(
        side_effect=lambda path, params=None: {
            "Organisation": {"Organisations": default_orgs},
            "Accounts": {"Accounts": accounts or []},
            "TaxRates": {"TaxRates": tax or []},
            "Contacts": {"Contacts": contacts or []},
            "Currencies": {"Currencies": currency_rows},
        }.get(path, {})
    )
    if currencies_error is not None:
        client.get_currencies = AsyncMock(side_effect=currencies_error)
    else:
        client.get_currencies = AsyncMock(return_value=list(currency_rows))
    monkeypatch.setattr(
        "app.services.integration.xero_sync_service.XeroClient",
        lambda **kwargs: client,
    )
    return client


@pytest.mark.asyncio
async def test_settings_sync_persists_accounts_and_tax_rates(db_session, monkeypatch):
    await _seed_connected(db_session)
    accounts = [
        {
            "AccountID": "acc-1",
            "Code": "200",
            "Name": "Sales",
            "Type": "REVENUE",
            "Status": "ACTIVE",
            "TaxType": "OUTPUT",
        },
        {
            "AccountID": "acc-2",
            "Code": "400",
            "Name": "Purchases",
            "Type": "EXPENSE",
            "Status": "ACTIVE",
            "TaxType": "INPUT",
        },
    ]
    tax = [
        {"TaxType": "OUTPUT", "Name": "GST on Income", "Status": "ACTIVE", "EffectiveRate": 10},
        {"TaxType": "INPUT", "Name": "GST on Expenses", "Status": "ACTIVE", "EffectiveRate": 10},
    ]
    _mock_xero_client(monkeypatch, accounts=accounts, tax=tax)

    result = await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()
    result = mark_sync_committed(result)

    assert result["committed"] is True
    assert result["accounts"]["fetched"] == 2
    assert result["accounts"]["created"] == 2
    assert result["accounts"]["persisted_total"] == 2
    assert result["tax_rates"]["created"] == 2
    assert result["currencies"]["created"] == 1

    db_count = (
        await db_session.execute(
            select(func.count()).select_from(XeroAccount).where(
                XeroAccount.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()
    assert int(db_count) == result["accounts"]["persisted_total"]

    totals = await get_master_data_totals(db_session, TESTING_TENANT_UUID)
    assert totals["accounts"] == 2
    assert totals["tax_rates"] == 2


@pytest.mark.asyncio
async def test_second_settings_sync_marks_unchanged(db_session, monkeypatch):
    await _seed_connected(db_session)
    accounts = [
        {
            "AccountID": "acc-1",
            "Code": "200",
            "Name": "Sales",
            "Type": "REVENUE",
            "Status": "ACTIVE",
        }
    ]
    tax = [{"TaxType": "OUTPUT", "Name": "GST", "Status": "ACTIVE", "EffectiveRate": 10}]
    _mock_xero_client(monkeypatch, accounts=accounts, tax=tax)

    await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()
    second = await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()

    assert second["accounts"]["created"] == 0
    assert second["accounts"]["unchanged"] == 1
    assert second["accounts"]["fetched"] == 1

    count = (
        await db_session.execute(
            select(func.count()).select_from(XeroAccount).where(
                XeroAccount.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()
    assert int(count) == 1


@pytest.mark.asyncio
async def test_missing_remote_account_deactivated(db_session, monkeypatch):
    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        accounts=[
            {"AccountID": "acc-1", "Code": "200", "Name": "Sales", "Status": "ACTIVE"},
            {"AccountID": "acc-2", "Code": "400", "Name": "Purchases", "Status": "ACTIVE"},
        ],
        tax=[],
    )
    await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()

    _mock_xero_client(
        monkeypatch,
        accounts=[{"AccountID": "acc-1", "Code": "200", "Name": "Sales", "Status": "ACTIVE"}],
        tax=[],
    )
    second = await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()
    assert second["accounts"]["deactivated"] == 1

    inactive = (
        await db_session.execute(
            select(XeroAccount).where(
                XeroAccount.tenant_id == TESTING_TENANT_UUID,
                XeroAccount.xero_account_id == "acc-2",
            )
        )
    ).scalar_one()
    assert inactive.sync_status == "inactive"


@pytest.mark.asyncio
async def test_contacts_synced_by_contact_id(db_session, monkeypatch):
    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        contacts=[
            {
                "ContactID": "c-1",
                "Name": "Acme Pty Ltd",
                "IsSupplier": True,
                "IsCustomer": False,
                "ContactStatus": "ACTIVE",
            }
        ],
    )
    result = mark_sync_committed(await sync_contacts(db_session, TESTING_TENANT_UUID))
    await db_session.commit()
    assert result["contacts"]["created"] == 1
    row = (
        await db_session.execute(
            select(XeroContact).where(XeroContact.xero_contact_id == "c-1")
        )
    ).scalar_one()
    assert row.name == "Acme Pty Ltd"
    assert row.is_supplier is True


@pytest.mark.asyncio
async def test_tenant_isolation_accounts_list(db_session):
    integration = await _seed_connected(db_session)
    other = uuid.uuid4()
    db_session.add(
        XeroAccount(
            tenant_id=TESTING_TENANT_UUID,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-1",
            xero_account_id="mine",
            code="100",
            name="Mine",
            sync_status="active",
        )
    )
    db_session.add(
        XeroAccount(
            tenant_id=other,
            accounting_integration_id=integration.id,
            xero_tenant_id="org-other",
            xero_account_id="theirs",
            code="999",
            name="Theirs",
            sync_status="active",
        )
    )
    await db_session.flush()
    listed = await list_xero_accounts(db_session, tenant_id=TESTING_TENANT_UUID)
    ids = {item["xero_account_id"] for item in listed["items"]}
    assert "mine" in ids
    assert "theirs" not in ids


@pytest.mark.asyncio
async def test_sync_job_records_counts(db_session, monkeypatch):
    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        accounts=[{"AccountID": "a1", "Code": "1", "Name": "A", "Status": "ACTIVE"}],
        tax=[{"TaxType": "NONE", "Name": "No Tax", "Status": "ACTIVE"}],
    )
    result = await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()
    job = (
        await db_session.execute(
            select(AccountingSyncJob).where(AccountingSyncJob.id == result["job_id"])
        )
    ).scalar_one()
    assert job.records_persisted >= 1
    assert job.direction == "inbound"
    assert job.status == "completed"


def test_payload_hash_stable():
    a = payload_hash({"Code": "200", "Name": "Sales"})
    b = payload_hash({"Name": "Sales", "Code": "200"})
    assert a == b


def test_entity_counters_persisted_total():
    c = EntitySyncCounters(created=2, updated=1, unchanged=3)
    assert c.to_dict()["persisted_total"] == 6


def test_mark_sync_committed_flag():
    payload = {"committed": False, "account": 1}
    assert mark_sync_committed(payload)["committed"] is True


@pytest.mark.asyncio
async def test_sync_settings_api_failure_marks_job_failed(db_session, monkeypatch):
    await _seed_connected(db_session)

    class Boom:
        def __init__(self, **kwargs):
            pass

        async def get_json(self, path, params=None):
            raise XeroApiError(status_code=500, error_code="boom", message="fail")

        async def get_currencies(self):
            raise XeroApiError(status_code=500, error_code="boom", message="fail")

    monkeypatch.setattr("app.services.integration.xero_sync_service.XeroClient", Boom)
    with pytest.raises(XeroApiError):
        await sync_settings(db_session, TESTING_TENANT_UUID)
    job = (
        await db_session.execute(
            select(AccountingSyncJob).order_by(AccountingSyncJob.id.desc()).limit(1)
        )
    ).scalar_one()
    assert job.status == "failed"


@pytest.mark.asyncio
async def test_currency_sync_persists_aud_from_currencies_api(db_session, monkeypatch):
    await _seed_connected(db_session)
    client = _mock_xero_client(
        monkeypatch,
        currencies=[{"Code": "AUD", "Description": "Australian Dollar"}],
        orgs=[{"OrganisationID": "org-1", "Name": "Demo Org", "BaseCurrency": "AUD"}],
    )
    result = mark_sync_committed(await sync_settings(db_session, TESTING_TENANT_UUID))
    await db_session.commit()

    assert result["currencies"]["fetched"] == 1
    assert result["currencies"]["created"] == 1
    assert result["currencies"]["updated"] == 0
    assert result["currencies"]["unchanged"] == 0
    assert result["currencies"]["failed"] == 0
    assert result["currencies"]["persisted_total"] == 1
    client.get_currencies.assert_awaited()

    row = (
        await db_session.execute(
            select(XeroCurrency).where(
                XeroCurrency.tenant_id == TESTING_TENANT_UUID,
                XeroCurrency.code == "AUD",
            )
        )
    ).scalar_one()
    assert row.sync_status == "active"
    assert row.xero_tenant_id == "org-1"


@pytest.mark.asyncio
async def test_currency_sync_persists_multiple_currencies(db_session, monkeypatch):
    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        currencies=[
            {"Code": "AUD", "Description": "Australian Dollar"},
            {"Code": "USD", "Description": "United States Dollar"},
            {"Code": "NZD", "Description": "New Zealand Dollar"},
        ],
    )
    result = mark_sync_committed(await sync_settings(db_session, TESTING_TENANT_UUID))
    await db_session.commit()

    assert result["currencies"]["fetched"] == 3
    assert result["currencies"]["created"] == 3
    assert result["currencies"]["persisted_total"] == 3
    codes = set(
        (
            await db_session.execute(
                select(XeroCurrency.code).where(
                    XeroCurrency.tenant_id == TESTING_TENANT_UUID,
                    XeroCurrency.sync_status == "active",
                )
            )
        ).scalars().all()
    )
    assert codes == {"AUD", "USD", "NZD"}


@pytest.mark.asyncio
async def test_currency_sync_repeated_is_idempotent(db_session, monkeypatch):
    await _seed_connected(db_session)
    currencies = [
        {"Code": "AUD", "Description": "Australian Dollar"},
        {"Code": "USD", "Description": "United States Dollar"},
    ]
    _mock_xero_client(monkeypatch, currencies=currencies)
    first = mark_sync_committed(await sync_settings(db_session, TESTING_TENANT_UUID))
    await db_session.commit()
    second = mark_sync_committed(await sync_settings(db_session, TESTING_TENANT_UUID))
    await db_session.commit()

    assert first["currencies"]["created"] == 2
    assert second["currencies"]["created"] == 0
    assert second["currencies"]["unchanged"] == 2
    assert second["currencies"]["fetched"] == 2
    assert second["currencies"]["persisted_total"] == 2
    count = (
        await db_session.execute(
            select(func.count()).select_from(XeroCurrency).where(
                XeroCurrency.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()
    assert int(count) == 2


@pytest.mark.asyncio
async def test_currency_api_failure_marks_sync_failed(db_session, monkeypatch):
    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        currencies_error=XeroApiError(
            status_code=503,
            error_code="currencies_unavailable",
            message="Currencies endpoint unavailable",
        ),
    )
    with pytest.raises(XeroApiError) as exc:
        await sync_settings(db_session, TESTING_TENANT_UUID)
    assert exc.value.error_code == "currencies_unavailable"
    job = (
        await db_session.execute(
            select(AccountingSyncJob).order_by(AccountingSyncJob.id.desc()).limit(1)
        )
    ).scalar_one()
    assert job.status == "failed"
    count = (
        await db_session.execute(
            select(func.count()).select_from(XeroCurrency).where(
                XeroCurrency.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()
    assert int(count) == 0


@pytest.mark.asyncio
async def test_currency_sync_tenant_isolation(db_session, monkeypatch):
    await _seed_connected(db_session)
    other_tenant = uuid.uuid4()
    from app.models.tenant import Tenant

    db_session.add(Tenant(id=other_tenant, name="Other", slug=f"other-{other_tenant.hex[:8]}"))
    await db_session.flush()
    other_integration = AccountingIntegration(
        tenant_id=other_tenant,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id="org-other",
        access_token_encrypted=encrypt_secret("access"),
        refresh_token_encrypted=encrypt_secret("refresh"),
    )
    db_session.add(other_integration)
    await db_session.flush()
    db_session.add(
        XeroCurrency(
            tenant_id=other_tenant,
            accounting_integration_id=other_integration.id,
            xero_tenant_id="org-other",
            code="USD",
            sync_status="active",
        )
    )
    await db_session.flush()

    _mock_xero_client(
        monkeypatch,
        currencies=[{"Code": "AUD", "Description": "Australian Dollar"}],
    )
    await sync_settings(db_session, TESTING_TENANT_UUID)
    await db_session.commit()

    ours = (
        await db_session.execute(
            select(XeroCurrency.code).where(XeroCurrency.tenant_id == TESTING_TENANT_UUID)
        )
    ).scalars().all()
    theirs = (
        await db_session.execute(
            select(XeroCurrency.code).where(XeroCurrency.tenant_id == other_tenant)
        )
    ).scalars().all()
    assert set(ours) == {"AUD"}
    assert set(theirs) == {"USD"}


@pytest.mark.asyncio
async def test_export_validation_accepts_aud_after_currency_sync(db_session, monkeypatch):
    """After Currencies API sync, export validation accepts organisation AUD."""
    from datetime import date
    from decimal import Decimal
    from unittest.mock import patch

    from app.models.invoice import Invoice, InvoiceStatus
    from app.models.line_item import LineItem
    from app.services.integration.accounting_mapping_service import upsert_mapping
    from app.models.accounting_entity_mapping import MAPPING_TAX
    from app.services.integration.xero_export_service import validate_invoice_for_xero_export

    await _seed_connected(db_session)
    _mock_xero_client(
        monkeypatch,
        accounts=[
            {
                "AccountID": "acc-400",
                "Code": "400",
                "Name": "Purchases",
                "Status": "ACTIVE",
                "TaxType": "INPUT",
            }
        ],
        tax=[{"TaxType": "INPUT", "Name": "GST on Expenses", "Status": "ACTIVE", "EffectiveRate": 10}],
        currencies=[{"Code": "AUD", "Description": "Australian Dollar"}],
    )
    sync_result = mark_sync_committed(await sync_settings(db_session, TESTING_TENANT_UUID))
    await db_session.commit()
    assert sync_result["currencies"]["persisted_total"] == 1

    await upsert_mapping(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        mapping_type=MAPPING_TAX,
        source_key="GST:10",
        external_code="INPUT",
        user_id=1,
        xero_tenant_id="org-1",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        invoice_no="INV-SYNC-1",
        invoice_date=date(2026, 1, 15),
        currency="",
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        gst_rate=Decimal("10"),
        total=Decimal("110.00"),
        status=InvoiceStatus.PROCESSED,
        account_code="400",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal("1"),
            unit_price=Decimal("100.00"),
            amount=Decimal("100.00"),
        )
    )
    await db_session.flush()

    with patch(
        "app.services.integration.xero_export_service.require_xero_ready",
        AsyncMock(return_value=(MagicMock(provider_tenant_id="org-1"), "org-1")),
    ):
        result = await validate_invoice_for_xero_export(
            db_session, tenant_id=TESTING_TENANT_UUID, invoice_id=inv.id
        )
    codes = {e["code"] for e in result["blocking_errors"]}
    assert "currency_not_supported" not in codes
    assert "currency_missing" not in codes
    assert result["canonical"]["currency"] == "AUD"
