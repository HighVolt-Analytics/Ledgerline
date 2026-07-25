"""Final purchase sync must not publish while status is still exception."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
from app.services.invoice.pipeline import (
    _halt_or_bypass_purchase_awaiting_po,
    _mark_invoice_processed,
)
from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(*, evaluation_status: str, status: InvoiceStatus = InvoiceStatus.EXCEPTION) -> Invoice:
    return Invoice(
        id=614,
        tenant_id=TESTING_TENANT_UUID,
        status=status,
        evaluation_status=evaluation_status,
        route_target="Purchase Management",
        po_reference="PO-250742524",
        currency="USD",
        total=18864,
    )


@pytest.mark.asyncio
async def test_awaiting_po_without_bypass_halts_as_exception(
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
    invoice = _invoice(evaluation_status=EVAL_AWAITING_PO)

    halted = await _halt_or_bypass_purchase_awaiting_po(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_po_hold=False,
    )

    assert halted is True
    assert invoice.status == InvoiceStatus.EXCEPTION
    assert invoice.evaluation_status == EVAL_AWAITING_PO
    notify.assert_called_once_with(invoice, InvoiceStatus.EXCEPTION)
    purge.assert_awaited_once()
    assert purge.await_args.kwargs["reason"] == "awaiting_po_hold"


@pytest.mark.asyncio
async def test_awaiting_po_bypass_restores_processed_for_publish(
    db_session: AsyncSession,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_AWAITING_PO)

    halted = await _halt_or_bypass_purchase_awaiting_po(
        db_session,
        invoice,
        bypass_review_gates=True,
        playbook_bypasses_po_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_playbook_override_captured_before_mark_processed_clears_it(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice.processing_override_catalog import (
        override_bypasses_purchase_hold,
    )

    invoice = _invoice(
        evaluation_status=EVAL_AWAITING_PO,
        status=InvoiceStatus.MAPPING,
    )
    invoice.processing_overrides = {"skip_steps": ["playbook"]}
    assert override_bypasses_purchase_hold(invoice)

    playbook_bypasses_po_hold = override_bypasses_purchase_hold(invoice)
    _mark_invoice_processed(invoice)
    assert not override_bypasses_purchase_hold(invoice)
    assert invoice.status == InvoiceStatus.PROCESSED

    # Simulate missing-PO sync flipping status back to exception.
    invoice.status = InvoiceStatus.EXCEPTION
    invoice.evaluation_status = EVAL_AWAITING_PO

    log_skip = AsyncMock()
    monkeypatch.setattr(
        "app.services.invoice.pipeline._log_processing_override_skip",
        log_skip,
    )

    halted = await _halt_or_bypass_purchase_awaiting_po(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_po_hold=playbook_bypasses_po_hold,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED
    log_skip.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_awaiting_po_processed_is_noop(db_session: AsyncSession) -> None:
    invoice = _invoice(
        evaluation_status=EVAL_AUTO_CODED,
        status=InvoiceStatus.PROCESSED,
    )

    halted = await _halt_or_bypass_purchase_awaiting_po(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_po_hold=False,
    )

    assert halted is False
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_exception_without_awaiting_flag_still_halts(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify = MagicMock(return_value=True)
    monkeypatch.setattr("app.services.invoice.pipeline.send_notification", notify)
    # Mimic bypass clearing evaluation_status but leaving EXCEPTION.
    invoice = _invoice(evaluation_status=EVAL_AUTO_CODED, status=InvoiceStatus.EXCEPTION)

    halted = await _halt_or_bypass_purchase_awaiting_po(
        db_session,
        invoice,
        bypass_review_gates=False,
        playbook_bypasses_po_hold=False,
    )

    assert halted is True
    assert invoice.status == InvoiceStatus.EXCEPTION
    assert invoice.evaluation_status == EVAL_AWAITING_PO
    notify.assert_called_once_with(invoice, InvoiceStatus.EXCEPTION)


@pytest.mark.asyncio
async def test_stop_if_not_processed_for_publish(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice.pipeline import _stop_if_not_processed_for_publish

    notify = MagicMock(return_value=True)
    monkeypatch.setattr("app.services.invoice.pipeline.send_notification", notify)
    invoice = _invoice(evaluation_status=None, status=InvoiceStatus.EXCEPTION)

    assert await _stop_if_not_processed_for_publish(db_session, invoice) is True
    notify.assert_called_once()

    invoice.status = InvoiceStatus.PROCESSED
    assert await _stop_if_not_processed_for_publish(db_session, invoice) is False
