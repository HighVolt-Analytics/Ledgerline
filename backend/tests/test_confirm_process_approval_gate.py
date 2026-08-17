"""Confirm & process must not skip document-type / team-expense approval."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.tenant_ids import TESTING_TENANT_UUID
from tests.approval_test_helpers import patch_approval_file_checks


@pytest.mark.asyncio
async def test_request_approval_rejects_processed_invoice(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Posted Co",
        invoice_no="P-1296",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="auto_coded",
        currency="MMK",
        file_hash="posted-req-1296",
        total=Decimal("340000"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.post(f"/api/approvals/{inv.id}/request")
    assert res.status_code == 400, res.text
    assert "posted" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_confirm_process_does_not_record_manager_approval(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_approval_file_checks(monkeypatch)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    pdf = upload_dir / "advance.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Khushi",
        invoice_no="3182",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target="Team Expenses",
        document_type_code="DT-05",
        currency="MMK",
        file_hash="confirm-advance-1296",
        raw_file_path=str(pdf),
        total=Decimal("340000"),
        team_expense_kind="advance_requisition",
    )
    db_session.add(inv)
    await db_session.flush()
    invoice_id = inv.id

    pipeline_calls: list[int] = []

    def _track_pipeline(ids, **kwargs):
        pipeline_calls.extend(ids)
        return "running"

    async def _noop_assert(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.approval.approval_api_service.ensure_stored_file_for_approval",
        _noop_assert,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service.assert_team_expense_approvable",
        _noop_assert,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service._assert_invoice_ready_for_approval",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.api.invoices.enqueue_invoice_pipelines",
        _track_pipeline,
    )

    res = await client.post(f"/api/invoices/{invoice_id}/confirm-process")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["status"] == "pending"
    assert pipeline_calls == [invoice_id]

    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == invoice_id)
        )
    ).scalars().all()
    assert "invoice_confirm_processed" in events
    assert "invoice_approved" not in events


@pytest.mark.asyncio
async def test_approve_still_records_manager_approval_after_confirm(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_approval_file_checks(monkeypatch)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    pdf = upload_dir / "advance-approve.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Khushi",
        invoice_no="3182-b",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target="Team Expenses",
        document_type_code="DT-05",
        currency="MMK",
        file_hash="approve-after-confirm",
        raw_file_path=str(pdf),
        total=Decimal("340000"),
        team_expense_kind="advance_requisition",
        account_name="Operating Expenses",
        account_code="6100",
    )
    db_session.add(inv)
    await db_session.flush()

    async def _noop_assert(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.approval.approval_api_service.assert_team_expense_approvable",
        _noop_assert,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_api_service._assert_invoice_ready_for_approval",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_posting_resumes",
        lambda ids, **kwargs: "running",
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_pipelines",
        lambda ids, **kwargs: "running",
    )

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200, res.text
    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "invoice_approved" in events
