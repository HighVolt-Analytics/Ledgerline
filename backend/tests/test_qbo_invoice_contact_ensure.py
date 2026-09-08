from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.qbo.contacts import ensure_invoice_qbo_contact
from app.models.qbo_contact import ENTITY_CUSTOMER, ENTITY_VENDOR
from app.schemas.document_type import DocumentTypeDefinition, resolved_counterparty_type
from app.tenant_ids import TESTING_TENANT_UUID


def _dt(*, route: str, counterparty_type: str) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-01",
        title="Test type",
        shortTitle="Test",
        klass="Transactional",
        posting="Yes",
        recognitionMode="signals",
        recognitionSignals=[],
        llmPrompt="",
        routeTarget=route,
        counterpartyType=counterparty_type,
        enabled=True,
        classifier={"enabled": False, "priority": 100, "confidence": 0.85},
    )


def _invoice(**kwargs):
    defaults = dict(
        id=1,
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        document_type_code="DT-01",
        abn="51824753556",
        email_sender="ap@acme.test",
        route_target="Purchase Management",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_sales_document_type_defaults_to_customer() -> None:
    row = DocumentTypeDefinition(
        code="DT-90",
        title="AR invoice",
        shortTitle="AR",
        klass="Transactional",
        posting="Yes",
        routeTarget="Sales Management",
        enabled=True,
        classifier={"enabled": False, "priority": 100, "confidence": 0.85},
    )
    assert row.counterparty_type == "customer"
    assert resolved_counterparty_type(row) == "customer"


def test_purchase_document_type_defaults_to_vendor() -> None:
    row = DocumentTypeDefinition(
        code="DT-91",
        title="AP invoice",
        shortTitle="AP",
        klass="Transactional",
        posting="Yes",
        routeTarget="Purchase Management",
        enabled=True,
        classifier={"enabled": False, "priority": 100, "confidence": 0.85},
    )
    assert row.counterparty_type == "vendor"


@pytest.mark.asyncio
async def test_ensure_skips_when_qbo_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.qbo.contacts.require_qbo_ready",
        AsyncMock(side_effect=RuntimeError("QuickBooks is not connected")),
    )
    monkeypatch.setattr("app.integrations.qbo.contacts.create_contact", create)
    assert await ensure_invoice_qbo_contact(AsyncMock(), _invoice()) is None
    create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_skips_empty_name(monkeypatch: pytest.MonkeyPatch) -> None:
    ready = AsyncMock()
    create = AsyncMock()
    monkeypatch.setattr("app.integrations.qbo.contacts.require_qbo_ready", ready)
    monkeypatch.setattr("app.integrations.qbo.contacts.create_contact", create)
    assert await ensure_invoice_qbo_contact(AsyncMock(), _invoice(vendor="")) is None
    ready.assert_not_called()
    create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_writes_vendor_from_document_type(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value={"created": True, "entity_type": ENTITY_VENDOR})
    monkeypatch.setattr(
        "app.integrations.qbo.contacts.require_qbo_ready",
        AsyncMock(return_value=(MagicMock(), "934145000")),
    )
    monkeypatch.setattr("app.integrations.qbo.contacts.create_contact", create)
    monkeypatch.setattr(
        "app.services.rule_book.rule_book_mapper.load_classification_config",
        AsyncMock(
            return_value=SimpleNamespace(
                document_types=[_dt(route="Purchase Management", counterparty_type="vendor")]
            )
        ),
    )
    result = await ensure_invoice_qbo_contact(AsyncMock(), _invoice())
    assert result is not None
    create.assert_awaited_once()
    assert create.await_args.kwargs["entity_type"] == ENTITY_VENDOR
    assert create.await_args.kwargs["display_name"] == "Acme Supplies"


@pytest.mark.asyncio
async def test_ensure_writes_customer_from_document_type(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value={"created": True, "entity_type": ENTITY_CUSTOMER})
    monkeypatch.setattr(
        "app.integrations.qbo.contacts.require_qbo_ready",
        AsyncMock(return_value=(MagicMock(), "934145000")),
    )
    monkeypatch.setattr("app.integrations.qbo.contacts.create_contact", create)
    monkeypatch.setattr(
        "app.services.rule_book.rule_book_mapper.load_classification_config",
        AsyncMock(
            return_value=SimpleNamespace(
                document_types=[_dt(route="Sales Management", counterparty_type="customer")]
            )
        ),
    )
    result = await ensure_invoice_qbo_contact(
        AsyncMock(),
        _invoice(route_target="Sales Management", vendor="Harbour View Hotel"),
    )
    assert result is not None
    assert create.await_args.kwargs["entity_type"] == ENTITY_CUSTOMER
    assert create.await_args.kwargs["display_name"] == "Harbour View Hotel"
