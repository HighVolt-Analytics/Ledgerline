"""Mobile GET /api/approvals must not 500 on deferred approval_chain heal."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval.approval_quorum_service import (
    _sync_safe_attr,
    ensure_invoice_approval_chain,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_sync_safe_attr_returns_default_for_unloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeState:
        unloaded = {"approval_chain"}
        dict = {"tenant_id": TESTING_TENANT_UUID}

    class _Obj:
        pass

    obj = _Obj()

    import sqlalchemy as sa

    real_inspect = sa.inspect

    def _fake_inspect(target):  # type: ignore[no-untyped-def]
        if target is obj:
            return _FakeState()
        return real_inspect(target)

    monkeypatch.setattr(sa, "inspect", _fake_inspect)
    assert _sync_safe_attr(obj, "approval_chain", None) is None
    assert _sync_safe_attr(obj, "tenant_id", None) == TESTING_TENANT_UUID


def test_ensure_chain_treats_unloaded_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    inv = SimpleNamespace(
        tenant_id=TESTING_TENANT_UUID,
        route_target="Team Expenses",
        total=500,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_quorum_service._sync_safe_attr",
        lambda obj, name, default=None: (
            default if name == "approval_chain" else getattr(obj, name, default)
        ),
    )
    assert ensure_invoice_approval_chain(inv) is True
    assert inv.approval_chain is not None


@pytest.mark.asyncio
async def test_list_approvals_survives_deferred_approval_chain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression for mobile "Could not load approvals".

    Generic list options defer approval_chain. Heal used to getattr() it and
    raise MissingGreenlet under AsyncSession → HTTP 500.
    """
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Mobile Queue Claim",
            status=InvoiceStatus.EXCEPTION,
            evaluation_status="pending_approval",
            document_type_code="DT-TE",
            route_target="Team Expenses",
            team_expense_kind="expense_claim",
            currency="AUD",
            total=Decimal("42.00"),
            document_text="ocr body that must stay deferred " * 100,
            extracted_fields={"manual_entry": "true", "without_document": "true"},
            approval_chain=None,
            file_hash="mobile-approvals-defer-heal",
            capture_source="upload",
        )
    )
    await db_session.flush()
    db_session.expire_all()

    res = await client.get("/api/approvals?page=1&page_size=100")
    assert res.status_code == 200, res.text
    body = res.json()
    rows = body.get("data") or body
    assert isinstance(rows, list)
    match = next((r for r in rows if r.get("vendor") == "Mobile Queue Claim"), None)
    assert match is not None
    assert match.get("approval_chain") is not None
