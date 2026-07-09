"""Approvals board should use lightweight invoice responses."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit import audit_service
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_approvals_board_skips_audit_hydration(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_audit(*_args, **_kwargs):
        raise AssertionError("audit_logs_for_invoices should not run for board")

    monkeypatch.setattr(audit_service, "audit_logs_for_invoices", _fail_audit)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="BRD-1",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="board-1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    rows = res.json()["data"]
    match = next((row for row in rows if row["id"] == inv.id), None)
    assert match is not None
    assert match["approval_board_column"] == "review"
