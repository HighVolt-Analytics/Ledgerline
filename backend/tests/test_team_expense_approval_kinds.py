"""Team Expenses kind-aware approval, budget skip, and spend counters."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.master_data import EmployeeBudget, EmployeeMasterResponse
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    TeamExpensePolicy,
)
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_APPROVAL, ROUTE_TEAM
from app.services.purchase.team_expense_approval import (
    apply_team_expense_approval_gate,
    assert_team_expense_amount_approvable,
    requires_manual_approval,
)
from app.services.purchase.team_expense_service import record_team_expense_processed
from app.services.purchase.team_expense_validator import vr_te02_budget
from app.tenant_ids import TESTING_TENANT_UUID


def _employee(*, monthly: float = 500.0, mtd: float = 0.0) -> EmployeeMasterResponse:
    return EmployeeMasterResponse(
        id="em-te-kind",
        name="Pat",
        email="pat@example.com",
        budget=EmployeeBudget(monthly=monthly, quarterly=0, annual=0, categories=[]),
        mtd_spent=mtd,
        qtd_spent=0,
        ytd_spent=0,
        status="Active",
        db_id=1,
    )


def test_advance_requisition_always_requires_approval_even_under_threshold() -> None:
    team_rule_policy = TeamExpensePolicy(auto_approve_below=50, require_receipt=False)
    # Minimal TeamExpenseRule-shaped object via Invoice only — pass None rule + playbook thr.
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        total=Decimal("20.00"),
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
    )
    assert requires_manual_approval(
        inv,
        None,
        manager_approved=False,
        playbook_auto_approve_below=50.0,
    )
    assert requires_manual_approval(
        inv,
        None,
        manager_approved=False,
        playbook_auto_approve_below=100.0,
    )
    assert not requires_manual_approval(
        inv,
        None,
        manager_approved=True,
        playbook_auto_approve_below=50.0,
    )
    _ = team_rule_policy


def test_te_approve_blocks_null_and_zero_amount() -> None:
    """Manager hold is not enough — a click-through would journal total-or-0."""
    missing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        total=None,
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
    )
    with pytest.raises(ValueError, match="missing or zero"):
        assert_team_expense_amount_approvable(missing)

    zero = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        total=Decimal("0.00"),
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
    )
    with pytest.raises(ValueError, match="missing or zero"):
        assert_team_expense_amount_approvable(zero)

    funded = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        total=Decimal("20000.00"),
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
    )
    assert_team_expense_amount_approvable(funded)


def test_expense_claim_respects_auto_approve_threshold(
    capture_config,
) -> None:
    from app.schemas.rule_book_config import TeamExpenseRule

    team_rule = capture_config.team_expense_rules[0].model_copy(
        update={"policy": TeamExpensePolicy(auto_approve_below=50, require_receipt=True)}
    )
    assert isinstance(team_rule, TeamExpenseRule)

    for kind in (TEAM_EXPENSE_KIND_CLAIM, None):
        small = Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            total=Decimal("20.00"),
            team_expense_kind=kind,
        )
        large = Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            total=Decimal("80.00"),
            team_expense_kind=kind,
        )
        assert not requires_manual_approval(small, team_rule, manager_approved=False)
        assert requires_manual_approval(large, team_rule, manager_approved=False)


def test_vr_te02_skipped_for_advance_requisition() -> None:
    emp = _employee(monthly=100.0, mtd=90.0)
    result = vr_te02_budget(
        emp, 50.0, team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE
    )
    assert result.passed
    assert result.skipped


def test_vr_te02_retired_for_claims() -> None:
    emp = _employee(monthly=100.0, mtd=90.0)
    result = vr_te02_budget(emp, 50.0, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM)
    assert result.passed
    assert result.skipped
    assert "gl account" in result.message.lower()


def test_legacy_against_advance_normalizes_to_claim_for_vr_te02() -> None:
    emp = _employee(monthly=100.0, mtd=90.0)
    result = vr_te02_budget(
        emp, 50.0, team_expense_kind="expense_against_advance"
    )
    assert result.passed
    assert result.skipped
    assert "gl account" in result.message.lower()


def test_vr_te03_skipped_for_advance_required_for_claim() -> None:
    from app.schemas.rule_book_config import (
        PostToAccounts,
        TeamExpensePolicy,
        TeamExpenseRule,
    )
    from app.services.purchase.team_expense_validator import vr_te03_receipt

    rule = TeamExpenseRule(
        id="te-1",
        name="Meals",
        enabled=True,
        priority=1,
        post_to=PostToAccounts(ledger="Meals"),
        policy=TeamExpensePolicy(auto_approve_below=30, require_receipt=True, receipt_threshold=0),
    )
    r3 = vr_te03_receipt(
        rule, 100.0, has_receipt_file=False, team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE
    )
    assert r3.passed and r3.skipped
    assert not vr_te03_receipt(
        rule, 100.0, has_receipt_file=False, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM
    ).passed


def test_vr_te04_bank_required_for_claim_and_advance() -> None:
    from app.schemas.master_data import BankDetails
    from app.services.purchase.team_expense_validator import vr_te04_bank

    emp = EmployeeMasterResponse(
        id="em-bank",
        name="Pat",
        email="pat@example.com",
        bank=BankDetails(),
        budget=EmployeeBudget(),
        status="Active",
        db_id=1,
    )
    # Legacy against-advance normalizes to claim — bank still required for reimbursement.
    legacy = vr_te04_bank(emp, team_expense_kind="expense_against_advance")
    assert not legacy.passed
    assert "reimbursement" in legacy.message
    claim = vr_te04_bank(emp, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM)
    assert not claim.passed
    assert "reimbursement" in claim.message
    advance = vr_te04_bank(emp, team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE)
    assert not advance.passed
    assert "advance payout" in advance.message


@pytest.mark.asyncio
async def test_apply_gate_holds_advance_under_threshold_with_reason(
    db_session: AsyncSession,
    capture_config,
) -> None:
    from app.services.rule_book.rule_book_config_repository import upsert_config

    # Ensure a category rule with high auto-approve so only kind forces the hold.
    rules = list(capture_config.team_expense_rules)
    if rules:
        rules[0] = rules[0].model_copy(
            update={"policy": TeamExpensePolicy(auto_approve_below=500, require_receipt=False)}
        )
    payload = capture_config.model_copy(update={"team_expense_rules": rules})
    await upsert_config(
        db_session,
        TESTING_TENANT_UUID,
        payload.model_dump(by_alias=True, mode="json"),
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        total=Decimal("20.00"),
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        status=InvoiceStatus.MAPPING,
        vendor="Staff",
        email_sender="ops@acme-hospitality.com.au",
        file_hash="te-advance-always-hold",
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_team_expense_approval_gate(db_session, inv)
    assert held is True
    assert inv.evaluation_status == EVAL_PENDING_APPROVAL
    assert inv.status == InvoiceStatus.EXCEPTION

    row = (
        await db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "team_expense_approval_required",
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one()
    detail = row.detail if isinstance(row.detail, dict) else {}
    assert detail.get("reason") == "advance_requisition_requires_approval"
    assert detail.get("team_expense_kind") == TEAM_EXPENSE_KIND_ADVANCE


@pytest.mark.asyncio
async def test_record_processed_skips_spend_for_advance(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-adv-spend",
            name="Ops Lead",
            email="ops-adv@acme-hospitality.com.au",
            spending_limits={"monthly": 5000, "quarterly": 12000, "annual": 45000, "categories": []},
            mtd_spent=100.0,
            ytd_spent=500.0,
            claim_count=2,
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Ops Lead",
        invoice_no="ADV-1",
        total=50.0,
        email_sender="ops-adv@acme-hospitality.com.au",
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        status=InvoiceStatus.PROCESSED,
        file_hash="te-adv-no-spend",
    )
    db_session.add(inv)
    await db_session.flush()

    await record_team_expense_processed(db_session, inv)

    row = (
        await db_session.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.master_id == "em-adv-spend"
            )
        )
    ).scalar_one()
    assert row.mtd_spent == 100.0
    assert row.ytd_spent == 500.0
    assert row.claim_count == 2


@pytest.mark.asyncio
async def test_record_processed_increments_spend_for_claim(
    db_session: AsyncSession,
) -> None:
    from datetime import date

    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-claim-spend",
            name="Ops Lead",
            email="ops-claim@acme-hospitality.com.au",
            spending_limits={"monthly": 5000, "quarterly": 12000, "annual": 45000, "categories": []},
            mtd_spent=100.0,
            ytd_spent=500.0,
            claim_count=2,
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Cafe",
        invoice_no="CLM-1",
        total=50.0,
        email_sender="ops-claim@acme-hospitality.com.au",
        employee_email="ops-claim@acme-hospitality.com.au",
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        status=InvoiceStatus.PROCESSED,
        file_hash="te-claim-spend",
        invoice_date=date.today(),
        currency="AUD",
    )
    db_session.add(inv)
    await db_session.flush()

    await record_team_expense_processed(db_session, inv)

    row = (
        await db_session.execute(
            select(EmployeeMasterRecord).where(
                EmployeeMasterRecord.master_id == "em-claim-spend"
            )
        )
    ).scalar_one()
    assert row.mtd_spent == 50.0
    assert row.ytd_spent == 50.0
    assert row.claim_count == 3


def test_soft_budget_overrun_forces_approval_even_below_threshold() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        total=Decimal("25"),
        status=InvoiceStatus.MAPPING,
        currency="AUD",
    )
    assert (
        requires_manual_approval(
            inv,
            None,
            manager_approved=False,
            playbook_auto_approve_below=100.0,
            soft_budget_overrun=False,
        )
        is False
    )
    assert (
        requires_manual_approval(
            inv,
            None,
            manager_approved=False,
            playbook_auto_approve_below=100.0,
            soft_budget_overrun=True,
        )
        is True
    )
