"""Regression: PROCESSED + auto_coded must not flip to needs_review on remap/re-eval."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_NEEDS_REVIEW,
    evaluate_invoice_routing,
)
from app.services.rule_book.rule_book_mapper import DOCUMENT_TYPE_RULE_TYPE, FALLBACK_RULE_TYPE
from app.tenant_ids import TESTING_TENANT_UUID


def _empty_config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload()


def _invoice(**kwargs) -> Invoice:
    base = dict(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.MAPPING,
        vendor="MakeMyTrip (India)",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        account_code="6100",
        account_name="Operating Expenses",
        route_target="Purchase Management",
        currency="INR",
    )
    base.update(kwargs)
    return Invoice(**base)


@pytest.fixture(autouse=True)
def _registration_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match staging path where vendor registration is waived for the DT."""
    monkeypatch.setattr(
        "app.services.master_data.vendor_registration_policy.vendor_registration_required",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        "app.services.master_data.vendor_registration_policy.customer_registration_required",
        lambda **_kwargs: False,
    )


def test_document_type_mapping_is_auto_coded_without_vendor_master() -> None:
    inv = _invoice(evaluation_status=EVAL_NEEDS_REVIEW)
    result = evaluate_invoice_routing(
        inv,
        _empty_config(),
        mapping_rule_type=DOCUMENT_TYPE_RULE_TYPE,
    )
    assert result.evaluation_status == EVAL_AUTO_CODED


def test_fallback_mapping_still_needs_review() -> None:
    inv = _invoice(
        vendor="Unknown Co",
        account_code="9999",
        evaluation_status=None,
        currency="AUD",
    )
    result = evaluate_invoice_routing(
        inv,
        _empty_config(),
        mapping_rule_type=FALLBACK_RULE_TYPE,
    )
    assert result.evaluation_status == EVAL_NEEDS_REVIEW


@pytest.mark.asyncio
async def test_apply_evaluation_does_not_reopen_processed_auto_coded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import invoice_evaluation_service as ies

    inv = _invoice(
        status=InvoiceStatus.PROCESSED,
        vendor="Betacarbon",
        document_type_confidence=0.85,
        evaluation_status=EVAL_AUTO_CODED,
        matched_rule_ids='["dt:DT-01"]',
        currency="USD",
    )

    monkeypatch.setattr(
        ies,
        "load_classification_config",
        AsyncMock(return_value=_empty_config()),
    )
    monkeypatch.setattr(
        ies,
        "classification_config_with_db_masters",
        AsyncMock(side_effect=lambda _s, _t, cfg: cfg),
    )
    monkeypatch.setattr(
        ies,
        "map_invoice_with_details",
        lambda _inv, config=None: type(
            "D",
            (),
            {"rule_type": FALLBACK_RULE_TYPE, "account_code": "9999"},
        )(),
    )
    monkeypatch.setattr(
        "app.services.master_data.customer_master_service.list_customer_masters",
        AsyncMock(return_value=[]),
    )

    result = await ies.apply_invoice_evaluation(
        AsyncMock(),
        inv,
        config=_empty_config(),
        enqueue_pending=False,
    )

    assert inv.evaluation_status == EVAL_AUTO_CODED
    assert result.evaluation_status == EVAL_AUTO_CODED


@pytest.mark.asyncio
async def test_apply_evaluation_preserves_pending_approval_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import invoice_evaluation_service as ies

    inv = _invoice(
        status=InvoiceStatus.EXCEPTION,
        vendor="Everest Furnishings",
        document_type_confidence=0.95,
        evaluation_status=ies.EVAL_PENDING_APPROVAL,
        matched_rule_ids='["dt:DT-03"]',
        currency="AUD",
        account_code="6100",
        account_name="Operating Expenses",
    )

    monkeypatch.setattr(
        ies,
        "load_classification_config",
        AsyncMock(return_value=_empty_config()),
    )
    monkeypatch.setattr(
        ies,
        "classification_config_with_db_masters",
        AsyncMock(side_effect=lambda _s, _t, cfg: cfg),
    )
    monkeypatch.setattr(
        ies,
        "map_invoice_with_details",
        lambda _inv, config=None: type(
            "D",
            (),
            {"rule_type": DOCUMENT_TYPE_RULE_TYPE, "account_code": "6100"},
        )(),
    )
    monkeypatch.setattr(
        "app.services.master_data.customer_master_service.list_customer_masters",
        AsyncMock(return_value=[]),
    )

    result = await ies.apply_invoice_evaluation(
        AsyncMock(),
        inv,
        config=_empty_config(),
        enqueue_pending=False,
    )

    assert inv.evaluation_status == ies.EVAL_PENDING_APPROVAL
    assert result.evaluation_status == ies.EVAL_PENDING_APPROVAL


@pytest.mark.asyncio
async def test_apply_evaluation_preserves_awaiting_po_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.invoice import invoice_evaluation_service as ies

    inv = _invoice(
        status=InvoiceStatus.EXCEPTION,
        vendor="Everest Furnishings",
        document_type_confidence=0.95,
        evaluation_status=ies.EVAL_AWAITING_PO,
        matched_rule_ids='["dt:DT-03"]',
        currency="AUD",
    )

    monkeypatch.setattr(
        ies,
        "load_classification_config",
        AsyncMock(return_value=_empty_config()),
    )
    monkeypatch.setattr(
        ies,
        "classification_config_with_db_masters",
        AsyncMock(side_effect=lambda _s, _t, cfg: cfg),
    )
    monkeypatch.setattr(
        ies,
        "map_invoice_with_details",
        lambda _inv, config=None: type(
            "D",
            (),
            {"rule_type": DOCUMENT_TYPE_RULE_TYPE, "account_code": "6100"},
        )(),
    )
    monkeypatch.setattr(
        "app.services.master_data.customer_master_service.list_customer_masters",
        AsyncMock(return_value=[]),
    )

    result = await ies.apply_invoice_evaluation(
        AsyncMock(),
        inv,
        config=_empty_config(),
        enqueue_pending=False,
    )

    assert inv.evaluation_status == ies.EVAL_AWAITING_PO
    assert result.evaluation_status == ies.EVAL_AWAITING_PO
