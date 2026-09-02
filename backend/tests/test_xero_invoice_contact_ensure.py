from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.integrations.xero.contacts import ensure_invoice_xero_supplier_contact
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, ROUTE_VAULT
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(**kwargs):
    defaults = dict(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        storage_vendor_slug="acme-supplies",
        abn="51824753556",
        email_sender="ap@acme.test",
        route_target="Purchase",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_ensure_skips_when_xero_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.xero.contacts.require_xero_ready",
        AsyncMock(side_effect=RuntimeError("Xero integration is not ready")),
    )
    monkeypatch.setattr("app.integrations.xero.contacts.create_xero_supplier_contact", create)
    result = await ensure_invoice_xero_supplier_contact(AsyncMock(), _invoice())
    assert result is None
    create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_skips_sales_and_empty_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock()
    ready = AsyncMock()
    monkeypatch.setattr("app.integrations.xero.contacts.require_xero_ready", ready)
    monkeypatch.setattr("app.integrations.xero.contacts.create_xero_supplier_contact", create)
    db = AsyncMock()
    assert await ensure_invoice_xero_supplier_contact(db, _invoice(route_target=ROUTE_SALES)) is None
    assert await ensure_invoice_xero_supplier_contact(db, _invoice(route_target=ROUTE_VAULT)) is None
    assert await ensure_invoice_xero_supplier_contact(db, _invoice(vendor="")) is None
    create.assert_not_called()
    ready.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_creates_or_reuses_xero_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    ready = AsyncMock(return_value=(object(), "org-1"))
    create = AsyncMock(return_value={"created": True, "contact_id": "c-1", "reused": False})
    monkeypatch.setattr("app.integrations.xero.contacts.require_xero_ready", ready)
    monkeypatch.setattr("app.integrations.xero.contacts.create_xero_supplier_contact", create)
    result = await ensure_invoice_xero_supplier_contact(AsyncMock(), _invoice())
    assert result["contact_id"] == "c-1"
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["legal_name"] == "Acme Supplies"
    assert kwargs["supplier_key"] == "acme-supplies"
    assert kwargs["tax_id"] == "51824753556"
