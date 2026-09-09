from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.qbo.contacts import resolve_cached_qbo_contact
from app.integrations.qbo.currencies import QboCurrencyWriteError
from app.integrations.qbo.export_masters import ensure_qbo_export_masters
from app.models.qbo_contact import ENTITY_CUSTOMER, ENTITY_VENDOR
from app.tenant_ids import TESTING_TENANT_UUID


def _row(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        qbo_entity_id=kwargs.get("qbo_entity_id", "56"),
        name=kwargs.get("name", "Acme Supplies"),
        tax_number=kwargs.get("tax_number"),
        email_address=kwargs.get("email_address"),
    )


def test_resolve_prefers_tax_id_then_name_then_email() -> None:
    rows = [
        _row(qbo_entity_id="1", name="Other Co", tax_number="51824753556"),
        _row(qbo_entity_id="2", name="Acme Supplies", email_address="ap@acme.test"),
    ]
    hit, reason = resolve_cached_qbo_contact(
        rows,
        display_name="Acme Supplies",
        tax_identifier="51 824 753 556",
        email="ap@acme.test",
    )
    assert hit is not None
    assert hit.qbo_entity_id == "1"
    assert reason == "tax_id"

    hit, reason = resolve_cached_qbo_contact(
        [_row(qbo_entity_id="2", name="Acme Supplies")],
        display_name="acme supplies",
        tax_identifier=None,
        email="ap@acme.test",
    )
    assert hit is not None and hit.qbo_entity_id == "2"
    assert reason == "name"

    hit, reason = resolve_cached_qbo_contact(
        [_row(qbo_entity_id="3", name="Different", email_address="ap@acme.test")],
        display_name="Unknown Pty",
        email="ap@acme.test",
    )
    assert hit is not None and hit.qbo_entity_id == "3"
    assert reason == "email"


def test_resolve_ambiguous_name_raises() -> None:
    rows = [
        _row(qbo_entity_id="1", name="Acme Supplies"),
        _row(qbo_entity_id="2", name="Acme  Supplies"),
    ]
    with pytest.raises(ValueError, match="ambiguous_vendor_match"):
        resolve_cached_qbo_contact(rows, display_name="Acme Supplies")


@pytest.mark.asyncio
async def test_export_masters_writes_contact_currency_and_tax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contact = AsyncMock(
        return_value={"created": True, "entity_type": ENTITY_VENDOR, "contact_id": "56"}
    )
    currency_row = SimpleNamespace(code="USD", name="United States Dollar")
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.require_qbo_ready",
        AsyncMock(return_value=(MagicMock(), "934145000")),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_invoice_qbo_contact",
        contact,
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_qbo_currency",
        AsyncMock(return_value=currency_row),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_invoice_qbo_tax_code",
        AsyncMock(
            return_value={
                "created": True,
                "tax_code_id": "99",
                "name": "GST 20%",
                "purchase_rate": "20.00",
            }
        ),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.resolve_invoice_qbo_gl_lines",
        AsyncMock(
            return_value={
                "parent_account_id": "1",
                "lines": [{"qbo_account_id": "11", "amount": "30.00", "kind": "sub"}],
            }
        ),
    )
    invoice = SimpleNamespace(
        id=9,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        currency="usd",
        gst_rate=20,
        gst=None,
    )
    result = await ensure_qbo_export_masters(AsyncMock(), invoice)
    contact.assert_awaited_once()
    assert result["contact"]["contact_id"] == "56"
    assert result["currency"]["code"] == "USD"
    assert result["tax"]["name"] == "GST 20%"
    assert result["gl"]["lines"][0]["qbo_account_id"] == "11"


@pytest.mark.asyncio
async def test_export_masters_skips_when_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contact = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.require_qbo_ready",
        AsyncMock(side_effect=RuntimeError("QuickBooks is not connected")),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_invoice_qbo_contact",
        contact,
    )
    result = await ensure_qbo_export_masters(
        AsyncMock(),
        SimpleNamespace(id=1, tenant_id=TESTING_TENANT_UUID, currency="AUD"),
    )
    assert result == {"contact": None, "currency": None, "tax": None, "gl": None}
    contact.assert_not_called()


@pytest.mark.asyncio
async def test_export_masters_does_not_raise_on_currency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.require_qbo_ready",
        AsyncMock(return_value=(MagicMock(), "934145000")),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_invoice_qbo_contact",
        AsyncMock(return_value={"created": True, "entity_type": ENTITY_CUSTOMER}),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_qbo_currency",
        AsyncMock(side_effect=QboCurrencyWriteError("Enable Multicurrency", status_code=409)),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.ensure_invoice_qbo_tax_code",
        AsyncMock(return_value={"created": False, "tax_code_id": "11", "name": "GST"}),
    )
    monkeypatch.setattr(
        "app.integrations.qbo.export_masters.resolve_invoice_qbo_gl_lines",
        AsyncMock(return_value=None),
    )
    result = await ensure_qbo_export_masters(
        AsyncMock(),
        SimpleNamespace(
            id=2,
            tenant_id=TESTING_TENANT_UUID,
            vendor="Hotel",
            currency="EUR",
            gst_rate=10,
        ),
    )
    assert result["contact"]["entity_type"] == ENTITY_CUSTOMER
    assert result["currency"] is None
    assert result["tax"]["tax_code_id"] == "11"
