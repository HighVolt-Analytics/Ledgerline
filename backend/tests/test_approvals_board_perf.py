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


@pytest.mark.asyncio
async def test_approvals_board_caps_queue_rows(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.approval import approval_api_service as svc

    monkeypatch.setattr(svc, "_BOARD_QUEUE_LIMIT", 2)
    for i in range(5):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor=f"Reject {i}",
                invoice_no=f"RJ-{i}",
                status=InvoiceStatus.REJECTED,
                currency="AUD",
                file_hash=f"board-cap-{i}",
            )
        )
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    queue_rows = [
        row
        for row in res.json()["data"]
        if row["status"] in {"rejected", "exception", "duplicate_skipped"}
    ]
    assert len(queue_rows) == 2


@pytest.mark.asyncio
async def test_approvals_board_skips_publish_lookup_for_exceptions(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.integration import publish_service

    seen: list[list[int]] = []
    original = publish_service.published_invoice_ids

    async def _wrap(session, invoice_ids, *, tenant_id=None):
        seen.append(list(invoice_ids))
        return await original(session, invoice_ids, tenant_id=tenant_id)

    monkeypatch.setattr(publish_service, "published_invoice_ids", _wrap)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold",
        invoice_no="EX-1",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="board-ex-pub",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    assert seen
    assert all(inv.id not in ids for ids in seen)


@pytest.mark.asyncio
async def test_approvals_board_includes_approval_chain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Quorum Co",
        invoice_no="Q-1",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="board-chain",
        approval_chain={"module": "purchase", "recorded": 1, "required": 2},
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    match = next(row for row in res.json()["data"] if row["id"] == inv.id)
    assert match["approval_chain"] == {"module": "purchase", "recorded": 1, "required": 2}


@pytest.mark.asyncio
async def test_approvals_board_status_queries_use_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import event

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Limit Co",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="board-limit-sql",
        )
    )
    await db_session.flush()

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        res = await client.get("/api/approvals/board")
        assert res.status_code == 200
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)

    invoice_selects = [
        s for s in statements if "from invoices" in s.lower() and "select" in s.lower()
    ]
    limited = [s for s in invoice_selects if " limit " in s.lower()]
    assert len(limited) >= 3, invoice_selects


@pytest.mark.asyncio
async def test_approvals_board_meta_counts_are_uncapped(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.approval import approval_api_service as svc

    monkeypatch.setattr(svc, "_BOARD_QUEUE_LIMIT", 2)
    for i in range(5):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor=f"Meta {i}",
                invoice_no=f"MT-{i}",
                status=InvoiceStatus.REJECTED,
                currency="AUD",
                file_hash=f"board-meta-{i}",
            )
        )
    await db_session.flush()

    res = await client.get("/api/approvals/board")
    assert res.status_code == 200
    body = res.json()
    queue_rows = [
        row
        for row in body["data"]
        if row["status"] in {"rejected", "exception", "duplicate_skipped"}
    ]
    assert len(queue_rows) == 2
    assert body["meta"]["approval_queue_count"] >= 5
    assert body["meta"]["approval_rejected_count"] >= 5
