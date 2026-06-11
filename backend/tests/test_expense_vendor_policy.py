"""Expenses Management vendor hold policy (amount-gated)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.rule_book_config import RuleBookConfigPayload, validate_rule_book_config_payload


@pytest.fixture
def capture_config() -> RuleBookConfigPayload:
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    return validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.expense_vendor_policy import (
    EVAL_UNMATCHED_EXPENSE_VENDOR,
    vendor_detection_evaluation_status,
)
from app.services.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_PENDING_VENDOR,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    evaluate_invoice_routing,
)
from app.services.vendor_hold_service import apply_vendor_hold_if_needed, invoice_is_vendor_held


def test_vendor_detection_high_confidence_no_flag() -> None:
    assert (
        vendor_detection_evaluation_status(
            route_target=ROUTE_EXPENSES,
            confidence=85,
            threshold=70,
            known_master=None,
            amount=200,
            hold_above=500,
        )
        is None
    )


def test_vendor_detection_small_unknown_expense_unmatched() -> None:
    assert (
        vendor_detection_evaluation_status(
            route_target=ROUTE_EXPENSES,
            confidence=10,
            threshold=70,
            known_master=None,
            amount=200,
            hold_above=500,
        )
        == EVAL_UNMATCHED_EXPENSE_VENDOR
    )


def test_vendor_detection_large_unknown_expense_pending() -> None:
    assert (
        vendor_detection_evaluation_status(
            route_target=ROUTE_EXPENSES,
            confidence=10,
            threshold=70,
            known_master=None,
            amount=600,
            hold_above=500,
        )
        == EVAL_PENDING_VENDOR
    )


def test_vendor_detection_team_route_never_flags() -> None:
    assert (
        vendor_detection_evaluation_status(
            route_target=ROUTE_TEAM,
            confidence=0,
            threshold=70,
            known_master=None,
            amount=600,
            hold_above=500,
        )
        is None
    )


def test_evaluate_routing_expense_small_unknown(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown SaaS Co",
        invoice_no="EXP-SMALL-001",
        total=Decimal("120.00"),
        route_target=ROUTE_EXPENSES,
        vendor_confidence=5.0,
        currency="AUD",
    )
    result = evaluate_invoice_routing(
        inv,
        capture_config,
        route_override=ROUTE_EXPENSES,
    )
    assert result.evaluation_status == EVAL_UNMATCHED_EXPENSE_VENDOR


def test_evaluate_routing_expense_large_unknown(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown SaaS Co",
        invoice_no="EXP-LARGE-001",
        total=Decimal("800.00"),
        route_target=ROUTE_EXPENSES,
        vendor_confidence=5.0,
        currency="AUD",
    )
    result = evaluate_invoice_routing(
        inv,
        capture_config,
        route_override=ROUTE_EXPENSES,
    )
    assert result.evaluation_status == EVAL_PENDING_VENDOR


def test_evaluate_routing_purchase_still_pending_vendor(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Unknown Supplier",
        invoice_no="PO-UNK-001",
        total=Decimal("120.00"),
        route_target=ROUTE_PURCHASE,
        vendor_confidence=5.0,
        currency="AUD",
    )
    result = evaluate_invoice_routing(
        inv,
        capture_config,
        route_override=ROUTE_PURCHASE,
    )
    assert result.evaluation_status == EVAL_PENDING_VENDOR


@pytest.mark.asyncio
async def test_unmatched_expense_vendor_not_pipeline_held(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Small Vendor Pty Ltd",
        route_target=ROUTE_EXPENSES,
        evaluation_status=EVAL_UNMATCHED_EXPENSE_VENDOR,
        status=InvoiceStatus.VALIDATING,
        total=Decimal("99.00"),
        currency="AUD",
        file_hash="exp-unmatched-1",
    )
    db_session.add(inv)
    await db_session.flush()

    assert not await invoice_is_vendor_held(db_session, inv)
    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert not held
    assert inv.status == InvoiceStatus.VALIDATING


@pytest.mark.asyncio
async def test_large_expense_unknown_still_held(db_session: AsyncSession) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Big Vendor Pty Ltd",
        route_target=ROUTE_EXPENSES,
        evaluation_status=EVAL_PENDING_VENDOR,
        status=InvoiceStatus.VALIDATING,
        total=Decimal("900.00"),
        currency="AUD",
        file_hash="exp-hold-1",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held
    assert inv.status == InvoiceStatus.EXCEPTION


def test_evaluate_routing_expense_matched_rule_auto_coded(capture_config) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Telstra Corporation",
        invoice_no="TEL-2026-4410",
        total=Decimal("189.00"),
        route_target=ROUTE_EXPENSES,
        vendor_confidence=95.0,
        currency="AUD",
    )
    result = evaluate_invoice_routing(
        inv,
        capture_config,
        route_override=ROUTE_EXPENSES,
    )
    assert result.evaluation_status == EVAL_AUTO_CODED
