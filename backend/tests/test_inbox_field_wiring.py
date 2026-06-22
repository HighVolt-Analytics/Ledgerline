"""Inbox column wiring: API fields ↔ rule book evaluation ↔ validation results."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.expense_vendor_policy import (
    EVAL_UNMATCHED_EXPENSE_VENDOR,
    expense_vendor_hold_above,
    vendor_detection_evaluation_status,
)
from app.services.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    apply_evaluation_to_invoice,
    evaluate_invoice_routing,
    load_config_for_tenant,
)
from app.services.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_engine import detect_vendor
from app.services.vendor_detection import find_matching_vendor_master


def _vr_pass(raw: str | None) -> int | None:
    if not raw:
        return None
    rules = json.loads(raw)
    evaluated = [r for r in rules if not r.get("skipped")]
    if not evaluated:
        return None
    passed = sum(1 for r in evaluated if r.get("passed"))
    return round(100 * passed / len(evaluated))


@pytest.mark.asyncio
async def test_list_invoices_exposes_inbox_columns(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        Invoice(
            tenant_id=1,
            vendor="Microsoft Azure",
            abn="31002882614",
            total=2288,
            status=InvoiceStatus.PROCESSED,
            evaluation_status=EVAL_AUTO_CODED,
            vendor_confidence=70.0,
            route_target="Expenses Management",
            validation_results=json.dumps(
                [
                    {"rule": "totals", "passed": True, "message": "ok", "skipped": False},
                    {"rule": "abn", "passed": True, "message": "ok", "skipped": False},
                ]
            ),
            currency="AUD",
            file_hash="inbox-wiring",
        )
    )
    await db_session.flush()

    res = await client.get("/api/invoices?page=1&page_size=20")
    assert res.status_code == 200
    row = next(item for item in res.json()["data"] if item["file_hash"] == "inbox-wiring")

    assert row["status"] == "processed"
    assert row["evaluation_status"] == "auto_coded"
    assert row["vendor_confidence"] == 70.0
    assert row["route_target"] == "Expenses Management"
    assert row["validation_results"] is not None
    passed = [r for r in row["validation_results"] if not r["skipped"] and r["passed"]]
    assert len(passed) == 2


@pytest.mark.asyncio
async def test_evaluation_status_matches_vendor_confidence_rules(
    db_session: AsyncSession,
) -> None:
    """Stored inbox fields must align with rule book vendor detection."""
    inv = Invoice(
        tenant_id=1,
        vendor="Unknown Cafe",
        total=120,
        status=InvoiceStatus.PROCESSED,
        route_target="Expenses Management",
        currency="AUD",
        file_hash="exp-unmatched",
    )
    db_session.add(inv)
    await db_session.flush()
    config = load_config_for_tenant(1)
    result = evaluate_invoice_routing(inv, config, route_override=inv.route_target)
    apply_evaluation_to_invoice(inv, result)

    threshold = config.vendor_detection_config.threshold
    hold = expense_vendor_hold_above(config)
    doc = invoice_to_eval_document(inv)
    vm = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
    known = find_matching_vendor_master(doc.vendor, doc.abn, config.vendor_masters)
    expected = vendor_detection_evaluation_status(
        route_target=inv.route_target,
        confidence=vm.confidence,
        threshold=threshold,
        known_master=known,
        amount=float(inv.total),
        hold_above=hold,
    )

    assert inv.vendor_confidence == vm.confidence
    if expected == EVAL_UNMATCHED_EXPENSE_VENDOR:
        assert inv.evaluation_status == EVAL_UNMATCHED_EXPENSE_VENDOR
        assert inv.vendor_confidence < threshold


@pytest.mark.asyncio
async def test_team_expenses_never_vendor_flagged_at_zero_confidence(
    db_session: AsyncSession,
) -> None:
    config = load_config_for_tenant(1)
    threshold = config.vendor_detection_config.threshold
    hold = expense_vendor_hold_above(config)
    flag = vendor_detection_evaluation_status(
        route_target="Team Expenses",
        confidence=0.0,
        threshold=threshold,
        known_master=None,
        amount=45.0,
        hold_above=hold,
    )
    assert flag is None


def test_validation_pass_rate_helper_matches_api_shape() -> None:
    """Mirror of frontend invoiceValidationConfidence over API validation_results."""
    raw = json.dumps(
        [
            {"rule": "a", "passed": True, "message": "", "skipped": False},
            {"rule": "b", "passed": False, "message": "", "skipped": False},
            {"rule": "c", "passed": True, "message": "", "skipped": True},
        ]
    )
    assert _vr_pass(raw) == 50
