"""Approve after quorum continues posting (resume), not full reprocess."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.tenant_ids import TESTING_TENANT_UUID
from tests.approval_test_helpers import patch_approval_file_checks


@pytest.mark.asyncio
async def test_team_expense_approve_enqueues_posting_resume(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approve must return quickly and defer mapping/journal to background."""
    patch_approval_file_checks(monkeypatch)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    pdf = upload_dir / "te-claim.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Uber",
        invoice_no="TE-724",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target="Team Expenses",
        currency="SGD",
        file_hash="te-approve-resume",
        raw_file_path=str(pdf),
        total=Decimal("2500"),
        account_name="Traveling",
        account_code="6200-01",
        team_expense_kind="expense_claim",
    )
    db_session.add(inv)
    await db_session.flush()

    resume_calls: list[int] = []
    pipeline_calls: list[int] = []

    def _track_resume(ids, **kwargs):
        resume_calls.extend(ids)
        return "running"

    def _track_pipeline(ids, **kwargs):
        pipeline_calls.extend(ids)
        return "running"

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
        _track_resume,
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_pipelines",
        _track_pipeline,
    )

    async def _fail_if_called(*_a, **_k):
        raise AssertionError("resume_invoice_posting_pipeline must not run inline")

    monkeypatch.setattr(
        "app.services.invoice.pipeline.resume_invoice_posting_pipeline",
        _fail_if_called,
    )

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["status"] == "mapping"
    assert resume_calls == [inv.id]
    assert pipeline_calls == []


@pytest.mark.asyncio
async def test_purchase_approve_enqueues_posting_resume_not_full_pipeline(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After quorum, purchase invoices continue posting — they do not full-reprocess."""
    patch_approval_file_checks(monkeypatch)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    pdf = upload_dir / "po-inv.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        invoice_no="PO-901",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target="Purchase Management",
        currency="USD",
        file_hash="purchase-approve-resume",
        raw_file_path=str(pdf),
        total=Decimal("1200"),
    )
    db_session.add(inv)
    await db_session.flush()

    resume_calls: list[int] = []
    pipeline_calls: list[int] = []

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
        lambda ids, **kwargs: resume_calls.extend(ids) or "running",
    )
    monkeypatch.setattr(
        "app.api.approvals.enqueue_invoice_pipelines",
        lambda ids, **kwargs: pipeline_calls.extend(ids) or "running",
    )

    res = await client.post(f"/api/approvals/{inv.id}/approve")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["status"] == "mapping"
    assert resume_calls == [inv.id]
    assert pipeline_calls == []
