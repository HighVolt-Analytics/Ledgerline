"""Final sales sync must not publish while status is still exception."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
from app.services.invoice.pipeline import (
    _halt_or_bypass_sales_awaiting_so,
    _mark_invoice_processed,
)
from app.services.sales.sales_document_service import EVAL_AWAITING_SO
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(*, evaluation_status: str, status: InvoiceStatus = InvoiceStatus.EXCEPTION) -> Invoice:
    return Invoice(
        id=715,
        tenant_id=TESTING_TENANT_UUID,
        status=status,
        evaluation_status=evaluation_status,
        route_target="Sales Management",
        so_reference="SO-250742524",
        currency="USD",
        total=18864,
    )


@pytest.mark.asyncio
async def test_awaiting_so_without_bypass_halts_as_exception(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify = MagicMock(return_value=True)
    purge = AsyncMock(return_value=2)
    monkeypatch.setattr("app.services.invoice.pipeline.send_notification", notify)
    monkeypatch.setattr(
        "app.services.invoice.pipeline.purge_accrual_journals_for_invoice",
        purge,
    )
    invoice = _invoice(evaluation_status=EVAL_AWAITING_SO)

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=False,
    )

    assert halted is True
    assert invoice.status == InvoiceStatus.EXCEPTION
    assert invoice.evaluation_status == EVAL_AWAITING_SO
    notify.assert_called_once_with(invoice, InvoiceStatus.EXCEPTION)
    purge.assert_awaited_once()
    assert purge.await_args.kwargs["reason"] == "awaiting_so_hold"


@pytest.mark.asyncio
async def test_non_sales_route_is_noop(db_session: AsyncSession) -> None:
    invoice = _invoice(evaluation_status=EVAL_AWAITING_SO, status=InvoiceStatus.EXCEPTION)
    invoice.route_target = "Purchase Management"

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=False,
    )

    assert halted is False


@pytest.mark.asyncio
async def test_awaiting_so_bypass_restores_processed_for_publish(
    db_session: AsyncSession,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_AWAITING_SO)

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=True,
        playbook_bypasses_so_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_playbook_override_captured_before_mark_processed_clears_it(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice.processing_override_catalog import override_bypasses_sales_hold

    invoice = _invoice(
        evaluation_status=EVAL_AWAITING_SO,
        status=InvoiceStatus.MAPPING,
    )
    invoice.processing_overrides = {"skip_steps": ["playbook"]}
    assert override_bypasses_sales_hold(invoice)

    playbook_bypasses_so_hold = override_bypasses_sales_hold(invoice)
    _mark_invoice_processed(invoice)
    assert not override_bypasses_sales_hold(invoice)
    assert invoice.status == InvoiceStatus.PROCESSED

    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_SO

    log_skip = AsyncMock()
    monkeypatch.setattr(
        "app.services.invoice.pipeline._log_processing_override_skip",
        log_skip,
    )

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=playbook_bypasses_so_hold,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED
    log_skip.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_awaiting_so_processed_is_noop(db_session: AsyncSession) -> None:
    invoice = _invoice(
        evaluation_status=EVAL_AUTO_CODED,
        status=InvoiceStatus.PROCESSED,
    )

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_exception_without_awaiting_flag_is_noop(
    db_session: AsyncSession,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_AUTO_CODED, status=InvoiceStatus.EXCEPTION)

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.EXCEPTION
    assert invoice.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_stale_awaiting_so_cleared_when_dt_match_does_not_require_so(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_AWAITING_SO)
    invoice.document_type_code = "DT-26"
    monkeypatch.setattr(
        "app.services.invoice.pipeline._dt_match_mode_requires_sales",
        AsyncMock(return_value=False),
    )

    halted = await _halt_or_bypass_sales_awaiting_so(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_so_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED
