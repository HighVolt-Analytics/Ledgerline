"""Risk-based approval routing — backward-compat and opt-in behavior."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_approval_service import apply_document_type_approval_gate
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL
from app.services.rule_book.validator import ValidationResult
from app.tenant_ids import TESTING_TENANT_UUID


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="Test",
        shortTitle="Test",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


@dataclass
class _GateMocks:
    session: AsyncMock
    log_event: AsyncMock


def _setup_gate_mocks(monkeypatch: pytest.MonkeyPatch) -> _GateMocks:
    session = AsyncMock()
    log_event = AsyncMock()
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.log_event",
        log_event,
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.latest_audit_detail_after_cycle_reset",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.approval.approval_quorum_service.ensure_invoice_approval_chain",
        lambda invoice: False,
    )
    return _GateMocks(session=session, log_event=log_event)


def _audit_reason(log_event: AsyncMock) -> str | None:
    if not log_event.await_args_list:
        return None
    detail = log_event.await_args_list[-1].kwargs.get("detail") or {}
    if isinstance(detail, dict):
        return str(detail.get("reason") or "")
    return None


def _audit_reasons(log_event: AsyncMock) -> list[str]:
    if not log_event.await_args_list:
        return []
    detail = log_event.await_args_list[-1].kwargs.get("detail") or {}
    if isinstance(detail, dict):
        raw = detail.get("reasons")
        if isinstance(raw, list):
            return [str(item) for item in raw]
    return []


# ---------------------------------------------------------------------------
# Phase A — backward compatibility (defaults must preserve today's behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_po_goods_no_po_holds_awaiting_po_not_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P-hold: invoice before PO waits for register — not Approvals match_not_clean."""
    from app.services.purchase.purchase_document_service import EVAL_AWAITING_PO

    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-09",
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 259
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("2838.00")
    invoice.purchase_document_type = "invoice"
    invoice.po_reference = "PO-MKT-2026-999"
    invoice.sales_document_type = None

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=None),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert invoice.evaluation_status == EVAL_AWAITING_PO
    assert mocks.log_event.await_args.args[1] == "purchase_awaiting_po"
    assert _audit_reason(mocks.log_event) == "missing_po_before_approval"


@pytest.mark.asyncio
async def test_po_goods_with_po_no_grn_still_match_not_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PO present but match unclean (e.g. No GRN) still goes to approval."""
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-09",
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 260
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("2838.00")
    invoice.purchase_document_type = "invoice"
    invoice.po_reference = "PO-MKT-2026-001"
    invoice.sales_document_type = None

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.load_purchase_order_for_invoice",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert invoice.evaluation_status == EVAL_PENDING_APPROVAL
    assert _audit_reason(mocks.log_event) == "match_not_clean"


@pytest.mark.asyncio
async def test_touchless_with_match_none_holds_for_amount_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Touchless when matched + Match none cannot prove clean — hold for Approvals."""
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 7
    invoice.tenant_id = TESTING_TENANT_UUID
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("100.00")
    invoice.approval_chain = None

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert invoice.evaluation_status == EVAL_PENDING_APPROVAL
    assert _audit_reason(mocks.log_event) == "no_match_basis"


@pytest.mark.asyncio
async def test_backward_compat_direct_expense_full_doa_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-08",
        playbookProfile="direct_expense",
        matchPolicy={"mode": "none"},
        approvalPolicy={"mode": "full_doa"},
    )
    invoice = MagicMock()
    invoice.id = 8
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("500.00")

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert _audit_reason(mocks.log_event) == "full_doa"


@pytest.mark.asyncio
async def test_backward_compat_ar_goods_2way_no_dn_held_match_not_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-12",
        playbookProfile="ar_goods_2way",
        routeTarget="Sales Management",
        matchPolicy={"mode": "two_way_dn_invoice"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 12
    invoice.tenant_id = None
    invoice.route_target = "Sales Management"
    invoice.total = Decimal("1000.00")
    invoice.sales_document_type = "invoice"
    invoice.so_reference = "SO-2026-001"
    invoice.purchase_document_type = None

    # SO exists — missing DN is match_not_clean, not awaiting_so.
    monkeypatch.setattr(
        "app.services.sales.sales_match_service.load_sales_order_for_invoice",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert _audit_reason(mocks.log_event) == "match_not_clean"


@pytest.mark.asyncio
async def test_ar_goods_no_so_holds_awaiting_so_not_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.sales.sales_document_service import EVAL_AWAITING_SO

    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-12",
        playbookProfile="ar_goods",
        routeTarget="Sales Management",
        matchPolicy={"mode": "three_way_so_dn"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 13
    invoice.tenant_id = None
    invoice.route_target = "Sales Management"
    invoice.total = Decimal("1000.00")
    invoice.sales_document_type = "invoice"
    invoice.so_reference = "SO-2026-999"
    invoice.purchase_document_type = None

    monkeypatch.setattr(
        "app.services.sales.sales_match_service.load_sales_order_for_invoice",
        AsyncMock(return_value=None),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert invoice.evaluation_status == EVAL_AWAITING_SO
    assert mocks.log_event.await_args.args[1] == "sales_awaiting_so"
    assert _audit_reason(mocks.log_event) == "missing_so_before_approval"


@pytest.mark.asyncio
async def test_backward_compat_supervisor_on_exception_clean_match_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="freight_logistics",
        matchPolicy={"mode": "shipment"},
        approvalPolicy={"mode": "supervisor_on_exception"},
    )
    invoice = MagicMock()
    invoice.id = 9
    invoice.route_target = "Purchase Management"

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=True),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False
    mocks.log_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_backward_compat_variance_workflow_holds_without_name_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={"mode": "variance_workflow"},
    )
    invoice = MagicMock()
    invoice.id = 99
    invoice.tenant_id = TESTING_TENANT_UUID
    invoice.route_target = "Purchase Management"
    invoice.approval_chain = None

    from app.services.match.match_variance_gate_service import MatchVarianceGateResult

    monkeypatch.setattr(
        "app.services.invoice.invoice_evaluation_service.load_config_for_tenant",
        AsyncMock(return_value=MagicMock(document_types=[], purchase_match=MagicMock())),
    )
    monkeypatch.setattr(
        "app.services.match.match_variance_gate_service.evaluate_match_variance_gate",
        AsyncMock(
            return_value=MatchVarianceGateResult(
                blocked=True,
                outcome=MagicMock(status="Price Variance"),
                variance_approved=False,
                anchor_number="PO-9",
                anchor_type="purchase",
                qty_tolerance_pct=0.0,
                match_mode="three_way_po_grn",
            )
        ),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert _audit_reason(mocks.log_event) == "match_variance_pending"


# ---------------------------------------------------------------------------
# Phase B — opt-in risk signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_approval_for_unmatched_holds_on_none_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "requireApprovalForUnmatched": True,
        },
    )
    invoice = MagicMock()
    invoice.id = 70
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("100.00")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._resolve_effective_match_tier",
        AsyncMock(return_value="none"),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert "unmatched_document" in _audit_reasons(mocks.log_event)


@pytest.mark.asyncio
async def test_require_approval_for_unmatched_default_holds_no_match_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = MagicMock()
    invoice.id = 71
    invoice.tenant_id = TESTING_TENANT_UUID
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("100.00")
    invoice.approval_chain = None

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert _audit_reason(mocks.log_event) == "no_match_basis"


@pytest.mark.asyncio
async def test_auto_approve_below_holds_at_threshold_even_with_clean_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "autoApproveBelow": 1000.0,
        },
    )
    invoice = MagicMock()
    invoice.id = 72
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("1000.00")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._resolve_effective_match_tier",
        AsyncMock(return_value="three_way_po_grn"),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert "amount_above_threshold" in _audit_reasons(mocks.log_event)


@pytest.mark.asyncio
async def test_auto_approve_below_passes_below_threshold_clean_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "autoApproveBelow": 1000.0,
        },
    )
    invoice = MagicMock()
    invoice.id = 73
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("999.99")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False


@pytest.mark.asyncio
async def test_unverified_counterparty_purchase_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "requireApprovalForUnverifiedCounterparty": True,
        },
    )
    invoice = MagicMock()
    invoice.id = 74
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("50.00")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._resolve_effective_match_tier",
        AsyncMock(return_value="three_way_po_grn"),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._touchless_match_satisfied",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=True),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert "unverified_counterparty" in _audit_reasons(mocks.log_event)


@pytest.mark.asyncio
async def test_unverified_counterparty_sales_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-26",
        playbookProfile="ar_goods",
        routeTarget="Sales Management",
        matchPolicy={"mode": "three_way_so_dn"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "requireApprovalForUnverifiedCounterparty": True,
        },
    )
    invoice = MagicMock()
    invoice.id = 75
    invoice.tenant_id = None
    invoice.route_target = "Sales Management"
    invoice.total = Decimal("50.00")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._resolve_effective_match_tier",
        AsyncMock(return_value="none"),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=True),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    assert "unverified_counterparty" in _audit_reasons(mocks.log_event)


@pytest.mark.asyncio
async def test_multiple_risk_reasons_combined_in_single_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "requireApprovalForUnmatched": True,
            "autoApproveBelow": 100.0,
        },
    )
    invoice = MagicMock()
    invoice.id = 76
    invoice.tenant_id = None
    invoice.route_target = "Purchase Management"
    invoice.total = Decimal("500.00")

    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service._resolve_effective_match_tier",
        AsyncMock(return_value="none"),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=False),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is True
    reasons = _audit_reasons(mocks.log_event)
    assert "unmatched_document" in reasons
    assert "amount_above_threshold" in reasons
    assert mocks.log_event.await_args_list[-1].kwargs.get("detail", {}).get("reason") == reasons[0]


@pytest.mark.asyncio
async def test_variance_workflow_holds_only_when_variance_gate_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={"mode": "variance_workflow"},
    )
    invoice = MagicMock()
    invoice.id = 77
    invoice.tenant_id = TESTING_TENANT_UUID
    invoice.route_target = "Purchase Management"
    invoice.approval_chain = None

    from app.services.match.match_variance_gate_service import MatchVarianceGateResult

    monkeypatch.setattr(
        "app.services.invoice.invoice_evaluation_service.load_config_for_tenant",
        AsyncMock(return_value=MagicMock(document_types=[], purchase_match=MagicMock())),
    )
    monkeypatch.setattr(
        "app.services.match.match_variance_gate_service.evaluate_match_variance_gate",
        AsyncMock(
            return_value=MatchVarianceGateResult(
                blocked=True,
                outcome=MagicMock(status="Qty Variance"),
                variance_approved=False,
                anchor_number="PO-1",
                anchor_type="purchase",
                qty_tolerance_pct=0.0,
                match_mode="three_way_po_grn",
            )
        ),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )

    assert held is True
    assert _audit_reason(mocks.log_event) == "match_variance_pending"


@pytest.mark.asyncio
async def test_variance_workflow_passes_when_no_blocking_variance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocks = _setup_gate_mocks(monkeypatch)
    definition = _definition(
        playbookProfile="po_goods",
        matchPolicy={"mode": "three_way_po_grn"},
        approvalPolicy={"mode": "variance_workflow"},
    )
    invoice = MagicMock()
    invoice.id = 78
    invoice.tenant_id = TESTING_TENANT_UUID
    invoice.route_target = "Purchase Management"

    from app.services.match.match_variance_gate_service import MatchVarianceGateResult

    monkeypatch.setattr(
        "app.services.invoice.invoice_evaluation_service.load_config_for_tenant",
        AsyncMock(return_value=MagicMock(document_types=[], purchase_match=MagicMock())),
    )
    monkeypatch.setattr(
        "app.services.match.match_variance_gate_service.evaluate_match_variance_gate",
        AsyncMock(
            return_value=MatchVarianceGateResult(
                blocked=False,
                outcome=None,
                variance_approved=False,
                anchor_number=None,
                anchor_type=None,
                qty_tolerance_pct=0.0,
                match_mode="three_way_po_grn",
            )
        ),
    )

    held = await apply_document_type_approval_gate(
        mocks.session,
        invoice,
        definition=definition,
        validation_results=[],
    )
    assert held is False
    mocks.log_event.assert_not_awaited()


# ---------------------------------------------------------------------------
# Verification — read-only trust, DT-07 integration, changelog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counterparty_requires_registration_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trust lookup must not enqueue holds or write audit events."""
    from app.services.master_data.counterparty_trust_service import (
        counterparty_requires_registration,
    )

    session = AsyncMock()
    invoice = MagicMock()
    invoice.route_target = "Purchase Management"

    monkeypatch.setattr(
        "app.services.master_data.vendor_hold_service._unknown_vendor_needs_registration",
        AsyncMock(return_value=True),
    )
    hold_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.master_data.vendor_hold_service.apply_vendor_hold_if_needed",
        hold_mock,
    )
    log_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.master_data.vendor_hold_service.log_event",
        log_mock,
    )

    result = await counterparty_requires_registration(session, invoice)

    assert result is True
    hold_mock.assert_not_awaited()
    log_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dt07_unmatched_opt_in_holds_with_real_match_resolver(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    DT-07-style invoice (match_mode none, touchless) auto-passes by default but
    holds when require_approval_for_unmatched is enabled — using the real resolver.
    """
    from decimal import Decimal

    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.classification.document_type_approval_service import (
        apply_document_type_approval_gate,
    )
    from app.services.purchase.purchase_match_service import resolve_purchase_match_context
    from app.tenant_ids import TESTING_TENANT_UUID

    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={
            "mode": "touchless_on_clean_match",
            "requireApprovalForUnmatched": True,
        },
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="HV-450",
        total=Decimal("450.00"),
        currency="AUD",
        route_target="Purchase Management",
        purchase_document_type="invoice",
        status=InvoiceStatus.VALIDATING,
        file_hash="dt07-risk-routing-test",
    )
    db_session.add(invoice)
    await db_session.flush()

    ctx = await resolve_purchase_match_context(db_session, invoice, requested_mode="none")
    assert ctx.effective_mode == "none"

    log_event = AsyncMock()
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.log_event",
        log_event,
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.counterparty_requires_registration",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.approval.approval_quorum_service.ensure_invoice_approval_chain",
        lambda inv: False,
    )

    held = await apply_document_type_approval_gate(
        db_session,
        invoice,
        definition=definition,
        validation_results=[],
    )

    assert held is True
    assert invoice.evaluation_status == EVAL_PENDING_APPROVAL
    assert "unmatched_document" in _audit_reasons(log_event)
    detail = log_event.await_args.kwargs.get("detail") or {}
    assert detail.get("resolved_match_tier") == "none"


@pytest.mark.asyncio
async def test_dt07_touchless_none_holds_no_match_basis_integration(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DT-07 touchless + match none holds — no match evidence to prove clean."""
    from decimal import Decimal

    from app.models.invoice import Invoice, InvoiceStatus
    from app.services.classification.document_type_approval_service import (
        apply_document_type_approval_gate,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    definition = _definition(
        code="DT-07",
        playbookProfile="standard_transactional",
        matchPolicy={"mode": "none"},
        approvalPolicy={"mode": "touchless_on_clean_match"},
    )
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="HV-451",
        total=Decimal("450.00"),
        currency="AUD",
        route_target="Purchase Management",
        purchase_document_type="invoice",
        status=InvoiceStatus.VALIDATING,
        file_hash="dt07-risk-routing-default",
    )
    db_session.add(invoice)
    await db_session.flush()

    log_event = AsyncMock()
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.has_document_approval",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.services.classification.document_type_approval_service.log_event",
        log_event,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_quorum_service.ensure_invoice_approval_chain",
        lambda inv: False,
    )

    held = await apply_document_type_approval_gate(
        db_session,
        invoice,
        definition=definition,
        validation_results=[],
    )

    assert held is True
    assert invoice.evaluation_status == EVAL_PENDING_APPROVAL
    assert _audit_reason(log_event) == "no_match_basis"

def test_rule_book_diff_detects_approval_policy_risk_field_change() -> None:
    """Risk field edits on a document type must appear in governance changelog diffs."""
    from app.services.rule_book.rule_book_audit import diff_rule_book_config

    before = {
        "document_types": [
            {
                "code": "DT-07",
                "title": "Standard invoice",
                "enabled": True,
                "playbook_profile": "standard_transactional",
                "match_policy": {"mode": "none"},
                "approval_policy": {"mode": "touchless_on_clean_match"},
            }
        ]
    }
    after = {
        "document_types": [
            {
                **before["document_types"][0],
                "approval_policy": {
                    "mode": "touchless_on_clean_match",
                    "require_approval_for_unmatched": True,
                },
            }
        ]
    }
    changes = diff_rule_book_config(before, after)
    assert "document_types" in changes
    assert "DT-07" in changes["document_types"]["modified"]
