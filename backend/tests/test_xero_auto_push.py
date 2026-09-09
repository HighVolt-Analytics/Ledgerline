from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.xero.auto_push import (
    _INFO_KEY,
    flush_scheduled_xero_auto_push,
    run_scheduled_xero_auto_push,
    schedule_xero_auto_push,
)
from app.models.invoice import InvoiceStatus
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, ROUTE_VAULT
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(**kwargs):
    defaults = dict(
        id=7,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_schedule_skips_sales_vault_and_unprocessed() -> None:
    session = SimpleNamespace(info={})
    schedule_xero_auto_push(session, _invoice(route_target=ROUTE_SALES))
    schedule_xero_auto_push(session, _invoice(route_target=ROUTE_VAULT))
    schedule_xero_auto_push(session, _invoice(status=InvoiceStatus.EXCEPTION))
    schedule_xero_auto_push(session, _invoice(id=None))
    assert not session.info.get(_INFO_KEY)


def test_schedule_queues_processed_ap_once() -> None:
    session = SimpleNamespace(info={})
    invoice = _invoice()
    schedule_xero_auto_push(session, invoice)
    schedule_xero_auto_push(session, invoice)
    assert session.info[_INFO_KEY] == [(str(TESTING_TENANT_UUID), 7)]


@pytest.mark.asyncio
async def test_run_skips_when_xero_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    db.get = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.database.db_session_with_rls", lambda _tid: _Ctx())
    monkeypatch.setattr(
        "app.integrations.xero.store.require_xero_ready",
        AsyncMock(side_effect=RuntimeError("Xero integration is not ready")),
    )
    export = AsyncMock()
    monkeypatch.setattr("app.integrations.xero.export.export_supplier_invoice_to_xero", export)

    result = await run_scheduled_xero_auto_push(TESTING_TENANT_UUID, 7)
    assert result is None
    export.assert_not_called()
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_run_swallows_export_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.xero.export import XeroExportError

    invoice = _invoice()
    db = MagicMock()
    db.get = AsyncMock(return_value=invoice)

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.database.db_session_with_rls", lambda _tid: _Ctx())
    monkeypatch.setattr(
        "app.integrations.xero.store.require_xero_ready",
        AsyncMock(return_value=(object(), "org-1")),
    )
    monkeypatch.setattr(
        "app.integrations.xero.export.export_supplier_invoice_to_xero",
        AsyncMock(side_effect=XeroExportError("validation failed", code="validation_failed")),
    )

    result = await run_scheduled_xero_auto_push(TESTING_TENANT_UUID, 7)
    assert result is None


@pytest.mark.asyncio
async def test_run_exports_when_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    invoice = _invoice()
    db = MagicMock()
    db.get = AsyncMock(return_value=invoice)

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.database.db_session_with_rls", lambda _tid: _Ctx())
    monkeypatch.setattr(
        "app.integrations.xero.store.require_xero_ready",
        AsyncMock(return_value=(object(), "org-1")),
    )
    export = AsyncMock(return_value={"skipped": False, "evidence": {"external_id": "x-1"}})
    monkeypatch.setattr("app.integrations.xero.export.export_supplier_invoice_to_xero", export)

    result = await run_scheduled_xero_auto_push(TESTING_TENANT_UUID, 7)
    assert result["evidence"]["external_id"] == "x-1"
    export.assert_awaited_once()
    kwargs = export.await_args.kwargs
    assert kwargs["invoice_id"] == 7
    assert kwargs["tenant_id"] == TESTING_TENANT_UUID
    assert kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_flush_awaits_queued_export(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[object, int]] = []

    async def _run(tenant_id, invoice_id):
        ran.append((tenant_id, invoice_id))
        return {"skipped": False}

    monkeypatch.setattr("app.integrations.xero.auto_push.run_scheduled_xero_auto_push", _run)
    session = SimpleNamespace(info={})
    schedule_xero_auto_push(session, _invoice())
    await flush_scheduled_xero_auto_push(session)
    assert ran == [(TESTING_TENANT_UUID, 7)]
    assert not session.info.get(_INFO_KEY)


@pytest.mark.asyncio
async def test_list_pending_keeps_ap_skips_sales() -> None:
    from app.integrations.xero.auto_push import list_pending_xero_auto_push_invoice_ids

    invoices = [
        _invoice(id=1, route_target="Purchase"),
        _invoice(id=2, route_target=ROUTE_SALES),
        _invoice(id=3, route_target=ROUTE_VAULT),
    ]
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = invoices
    db.execute = AsyncMock(return_value=result)
    ids = await list_pending_xero_auto_push_invoice_ids(db, TESTING_TENANT_UUID)
    assert ids == [1]


@pytest.mark.asyncio
async def test_replay_skips_when_xero_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.xero.auto_push import replay_pending_xero_exports

    db = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.database.db_session_with_rls", lambda _tid: _Ctx())
    monkeypatch.setattr(
        "app.integrations.xero.store.require_xero_ready",
        AsyncMock(side_effect=RuntimeError("not connected")),
    )
    result = await replay_pending_xero_exports(TESTING_TENANT_UUID)
    assert result == {"attempted": 0, "succeeded": 0, "skipped_not_connected": 1}


@pytest.mark.asyncio
async def test_replay_pushes_pending_invoices_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.xero.auto_push import replay_pending_xero_exports

    db = AsyncMock()

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    ran: list[int] = []

    async def _run(_tenant_id, invoice_id):
        ran.append(invoice_id)
        return {"skipped": False}

    monkeypatch.setattr("app.database.db_session_with_rls", lambda _tid: _Ctx())
    monkeypatch.setattr(
        "app.integrations.xero.store.require_xero_ready",
        AsyncMock(return_value=(object(), "org-1")),
    )
    monkeypatch.setattr(
        "app.integrations.xero.auto_push.list_pending_xero_auto_push_invoice_ids",
        AsyncMock(return_value=[4, 9]),
    )
    monkeypatch.setattr("app.integrations.xero.auto_push.run_scheduled_xero_auto_push", _run)
    result = await replay_pending_xero_exports(TESTING_TENANT_UUID)
    assert ran == [4, 9]
    assert result == {"attempted": 2, "succeeded": 2, "skipped_not_connected": 0}
