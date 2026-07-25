from unittest.mock import AsyncMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_VENDOR,
)
from app.services.invoice.pipeline import _mark_deterministic_mapping_auto_coded
from app.services.rule_book.account_mapper import MappingDetail
from app.services.rule_book.rule_book_mapper import (
    DOCUMENT_TYPE_RULE_TYPE,
    FALLBACK_RULE_TYPE,
)
from app.tenant_ids import TESTING_TENANT_UUID


def _invoice(*, evaluation_status: str) -> Invoice:
    return Invoice(
        id=656,
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.MAPPING,
        evaluation_status=evaluation_status,
        document_type_code="DT-04",
        account_code="6100",
        account_name="Operating Expenses",
        currency="INR",
    )


def _mapping(rule_type: str) -> MappingDetail:
    return MappingDetail(
        expense_category="Operating Expenses",
        account_code="6100",
        account_name="Operating Expenses",
        rule_type=rule_type,
        match_reason="Document type DT-04: Non-PO vendor invoice",
    )


@pytest.mark.asyncio
async def test_deterministic_dt_mapping_closes_coding_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    loaded = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    log = AsyncMock()
    monkeypatch.setattr("app.services.invoice.pipeline.log_event", log)

    changed = await _mark_deterministic_mapping_auto_coded(
        AsyncMock(),
        invoice,
        loaded,
        _mapping(DOCUMENT_TYPE_RULE_TYPE),
    )

    assert changed is True
    assert invoice.evaluation_status == EVAL_AUTO_CODED
    assert loaded.evaluation_status == EVAL_AUTO_CODED
    assert log.await_args.args[1] == "evaluation_auto_coded"
    assert log.await_args.kwargs["detail"]["reason"] == "deterministic_gl_mapping"


@pytest.mark.asyncio
async def test_fallback_mapping_remains_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    loaded = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    log = AsyncMock()
    monkeypatch.setattr("app.services.invoice.pipeline.log_event", log)

    changed = await _mark_deterministic_mapping_auto_coded(
        AsyncMock(),
        invoice,
        loaded,
        _mapping(FALLBACK_RULE_TYPE),
    )

    assert changed is False
    assert invoice.evaluation_status == EVAL_NEEDS_REVIEW
    assert loaded.evaluation_status == EVAL_NEEDS_REVIEW
    log.assert_not_awaited()


@pytest.mark.asyncio
async def test_deterministic_mapping_does_not_override_vendor_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice = _invoice(evaluation_status=EVAL_PENDING_VENDOR)
    loaded = _invoice(evaluation_status=EVAL_PENDING_VENDOR)
    log = AsyncMock()
    monkeypatch.setattr("app.services.invoice.pipeline.log_event", log)

    changed = await _mark_deterministic_mapping_auto_coded(
        AsyncMock(),
        invoice,
        loaded,
        _mapping(DOCUMENT_TYPE_RULE_TYPE),
    )

    assert changed is False
    assert invoice.evaluation_status == EVAL_PENDING_VENDOR
    assert loaded.evaluation_status == EVAL_PENDING_VENDOR
    log.assert_not_awaited()


def test_mark_processed_normalizes_stale_needs_review() -> None:
    """Invariant: PROCESSED ⇒ coding review closed (needs_review → auto_coded)."""
    from app.services.invoice.pipeline import _mark_invoice_processed

    invoice = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    _mark_invoice_processed(invoice)
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_AUTO_CODED


def test_mark_processed_preserves_non_review_evaluation() -> None:
    from app.services.invoice.pipeline import _mark_invoice_processed

    invoice = _invoice(evaluation_status=EVAL_PENDING_VENDOR)
    _mark_invoice_processed(invoice)
    assert invoice.status == InvoiceStatus.PROCESSED
    assert invoice.evaluation_status == EVAL_PENDING_VENDOR
