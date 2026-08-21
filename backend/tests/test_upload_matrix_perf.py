"""Upload workspace matrix query-volume regressions (perf/upload-optimization)."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_matrix_default_page_skips_duplicate_unfiltered_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Upload Co",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="upload-matrix-count",
        )
    )
    await db_session.flush()

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        res = await client.get("/api/matrix?page=1&page_size=10")
        assert res.status_code == 200
        body = res.json()
        assert body["meta"]["total"] == body["meta"]["matrix_document_count"]
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)

    invoice_counts = sum(
        1
        for s in statements
        if "count(" in str(s).lower() and "from invoices" in str(s).lower()
    )
    # Page COUNT + combined flagged/duplicates. Awaiting may still count invoices.
    # Default used to add a third identical unfiltered COUNT.
    assert 1 <= invoice_counts <= 4, invoice_counts
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_matrix_hydrates_stage_audit_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.reports import matrix_service as ms

    captured: dict[str, object] = {}
    original = ms.audit_logs_for_invoice_ids

    async def _wrap(db, invoice_ids, *, tenant_id, per_invoice_limit=None, events=None):
        captured["limit"] = per_invoice_limit
        captured["events"] = events
        return await original(
            db,
            invoice_ids,
            tenant_id=tenant_id,
            per_invoice_limit=per_invoice_limit,
            events=events,
        )

    monkeypatch.setattr(ms, "audit_logs_for_invoice_ids", _wrap)

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Audit Co",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="upload-matrix-audit",
        )
    )
    await db_session.flush()

    res = await client.get("/api/matrix?page=1&page_size=10")
    assert res.status_code == 200
    events = captured.get("events")
    assert isinstance(events, (set, frozenset))
    assert captured["limit"] == 24
    assert "mapping_applied" in events
    assert "invoice_approved" in events
    assert "ocr_page_extracted" not in events


@pytest.mark.asyncio
async def test_matrix_does_not_load_full_classification_config(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.invoice import invoice_evaluation_service as evaluation
    from app.services.rule_book import rule_book_mapper as mapper

    async def _boom(*_args, **_kwargs):
        raise AssertionError("matrix list must not load full classification config")

    monkeypatch.setattr(evaluation, "load_config_for_tenant", _boom)
    monkeypatch.setattr(mapper, "load_classification_config", _boom)

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Config Co",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="upload-matrix-config",
        )
    )
    await db_session.flush()

    res = await client.get("/api/matrix?page=1&page_size=10")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_mailbox_list_includes_document_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.connected_mailbox import ConnectedMailbox

    mailbox = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email="upload-count@example.com",
        display_name="Upload Count",
        is_active=True,
    )
    db_session.add(mailbox)
    await db_session.flush()
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            connected_mailbox_id=mailbox.id,
            vendor="Mailbox Co",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="upload-mailbox-count",
        )
    )
    await db_session.flush()

    res = await client.get("/api/mailboxes")
    assert res.status_code == 200
    rows = res.json()["data"]
    match = next(row for row in rows if row["email"] == "upload-count@example.com")
    assert match["document_count"] == 1
