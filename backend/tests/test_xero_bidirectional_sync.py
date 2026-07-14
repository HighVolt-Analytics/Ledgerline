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


def _mock_xero_client(monkeypatch: pytest.MonkeyPatch, *, accounts=None, tax=None, contacts=None, orgs=None):
    client = MagicMock()
    client.get_json = AsyncMock(
        side_effect=lambda path, params=None: {
            "Organisation": {
                "Organisations": orgs
                or [
                    {
                        "OrganisationID": "org-1",
                        "Name": "Demo Org",
                        "Currencies": [{"Code": "AUD", "Description": "Australian Dollar"}],
                    }
                ]
            },
            "Accounts": {"Accounts": accounts or []},
            "TaxRates": {"TaxRates": tax or []},
            "Contacts": {"Contacts": contacts or []},
        }.get(path, {})
    )
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

    monkeypatch.setattr("app.services.integration.xero_sync_service.XeroClient", Boom)
    with pytest.raises(XeroApiError):
        await sync_settings(db_session, TESTING_TENANT_UUID)
    job = (
        await db_session.execute(
            select(AccountingSyncJob).order_by(AccountingSyncJob.id.desc()).limit(1)
        )
    ).scalar_one()
    assert job.status == "failed"
