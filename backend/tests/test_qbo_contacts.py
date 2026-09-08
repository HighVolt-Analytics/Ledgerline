"""QuickBooks pulled-contact sync and create."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from sqlalchemy import select

from app.integrations.qbo.contacts import create_vendor, list_contacts, sync_contacts
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.qbo_contact import QboContact
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


def _mock_http(monkeypatch: pytest.MonkeyPatch, *, get_payload: dict, post_payload: dict | None = None) -> None:
    get_response = MagicMock()
    get_response.status_code = 200
    get_response.json.return_value = get_payload
    get_response.content = b"{}"
    post_response = MagicMock()
    post_response.status_code = 200
    post_response.json.return_value = post_payload or {}
    post_response.content = b"{}"
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=get_response)
    mock_client.post = AsyncMock(return_value=post_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.integrations.qbo.client.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )


@pytest.mark.asyncio
async def test_sync_contacts_persists_vendors_and_customers(
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
                    "Vendor": [
                        {
                            "Id": "56",
                            "DisplayName": "Acme Pty Ltd",
                            "Active": True,
                            "PrimaryEmailAddr": {"Address": "ap@acme.test"},
                        }
                    ]
                }
            }
            if calls["n"] == 1
            else {
                "QueryResponse": {
                    "Customer": [
                        {
                            "Id": "12",
                            "DisplayName": "Retail Buyer",
                            "Active": True,
                        }
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

    result = await sync_contacts(db_session, TESTING_TENANT_UUID)
    assert result["contact"] == 2
    listed = await list_contacts(db_session, tenant_id=TESTING_TENANT_UUID, limit=50, offset=0)
    names = {item["name"] for item in listed["items"]}
    assert names == {"Acme Pty Ltd", "Retail Buyer"}
    types = {item["entity_type"] for item in listed["items"]}
    assert types == {"vendor", "customer"}


@pytest.mark.asyncio
async def test_create_vendor_writes_to_quickbooks(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(_connected_qbo())
    await db_session.flush()
    _mock_http(
        monkeypatch,
        get_payload={"QueryResponse": {}},
        post_payload={"Vendor": {"Id": "99", "DisplayName": "New Supplier", "Active": True}},
    )
    created = await create_vendor(
        db_session, tenant_id=TESTING_TENANT_UUID, display_name="New Supplier"
    )
    assert created["created"] is True
    assert created["contact_id"] == "99"
    row = (
        await db_session.execute(select(QboContact).where(QboContact.qbo_entity_id == "99"))
    ).scalar_one()
    assert row.name == "New Supplier"
    assert row.is_supplier is True
