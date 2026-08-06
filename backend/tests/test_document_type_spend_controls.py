"""Document-type budgetControl / advanceControl gates for employee-level checks."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_CLAIM,
    ChartOfAccountEntry,
    PostingDefaults,
    RuleBookConfigPayload,
    TeamExpensePostingDefaults,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.purchase.team_expense_kind_service import resolve_default_team_expense_kind
from app.services.purchase.team_expense_validator import (
    document_type_spend_controls,
    run_team_expense_validations,
)
from app.services.rule_book.rule_book_config_io import save_rule_book_config
from app.tenant_ids import TESTING_TENANT_UUID

EMP_EMAIL = "spend.ctrl@example.com"


def _dt(
    code: str,
    *,
    budget_control: bool = True,
    advance_control: bool = True,
    team_expense_kind: str = "",
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=f"{code} title",
        shortTitle=code,
        klass="Transactional",
        posting="Yes",
        routeTarget=ROUTE_TEAM,
        playbookProfile="employee_claim",
        teamExpenseKind=team_expense_kind,
        budgetControl=budget_control,
        advanceControl=advance_control,
        postTo={"ledger": "Travel Expense"},
    )


def _config(*document_types: DocumentTypeDefinition) -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        team_expense_posting=TeamExpensePostingDefaults(
            default_advance_parent_ledger="Staff Advance",
            settlement_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1300", name="Staff Advance", type="Asset"),
            ChartOfAccountEntry(code="5000", name="Travel Expense", type="Expense"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
        document_types=list(document_types),
    )


def test_document_type_spend_controls_defaults_and_flags() -> None:
    config = _config(_dt("DT-BUD", budget_control=False, advance_control=True))
    # No / unknown DT → legacy enforce both.
    assert document_type_spend_controls(config, None) == (True, True)
    assert document_type_spend_controls(config, "missing") == (True, True)
    assert document_type_spend_controls(config, "DT-BUD") == (False, True)

    config2 = _config(_dt("DT-ADV", budget_control=True, advance_control=False))
    assert document_type_spend_controls(config2, "DT-ADV") == (True, False)

    # Explicit DT with both off (blank-type default).
    config3 = _config(_dt("DT-OFF", budget_control=False, advance_control=False))
    assert document_type_spend_controls(config3, "DT-OFF") == (False, False)


@pytest.mark.asyncio
async def test_budget_control_off_skips_employee_budget_rules(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(
        db_session,
        _config(_dt("DT-NOBUD", budget_control=False)),
        TESTING_TENANT_UUID,
    )
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-nobud",
            name="No Bud",
            email=EMP_EMAIL,
            spending_limits={"monthly": 10, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            bank={"account_number": "123"},
            mtd_spent=9,
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        total=Decimal("50"),
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        employee_email=EMP_EMAIL,
        email_sender=EMP_EMAIL,
        document_type_code="DT-NOBUD",
        file_hash="dt-nobud-1",
        raw_file_path="r.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    data = InvoiceData(
        vendor="Cafe",
        abn=None,
        invoice_no="NB-1",
        invoice_date=None,
        due_date=None,
        total=Decimal("50"),
        currency="AUD",
        line_items=[],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender=EMP_EMAIL,
        employee_email=EMP_EMAIL,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        has_receipt_file=True,
        invoice=inv,
    )
    by_rule = {r.rule: r for r in results}
    assert by_rule["VR-TE02"].passed and by_rule["VR-TE02"].skipped
    assert by_rule["VR-TE06"].passed and by_rule["VR-TE06"].skipped
    assert by_rule["VR-TE08"].passed and by_rule["VR-TE08"].skipped
    assert "budget control off" in by_rule["VR-TE02"].message.lower()


@pytest.mark.asyncio
async def test_advance_control_off_skips_advance_balance_rule(
    db_session: AsyncSession,
) -> None:
    await save_rule_book_config(
        db_session,
        _config(_dt("DT-NOADV", advance_control=False)),
        TESTING_TENANT_UUID,
    )
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-noadv",
            name="No Adv",
            email=EMP_EMAIL,
            spending_limits={"monthly": 5000, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            bank={"account_number": "123"},
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        total=Decimal("9999"),
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        employee_email=EMP_EMAIL,
        email_sender=EMP_EMAIL,
        document_type_code="DT-NOADV",
        file_hash="dt-noadv-1",
        raw_file_path="r.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    data = InvoiceData(
        vendor="Taxi",
        abn=None,
        invoice_no="NA-1",
        invoice_date=None,
        due_date=None,
        total=Decimal("9999"),
        currency="AUD",
        line_items=[],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender=EMP_EMAIL,
        employee_email=EMP_EMAIL,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        has_receipt_file=True,
        invoice=inv,
    )
    te07 = next(r for r in results if r.rule == "VR-TE07")
    assert te07.passed and te07.skipped
    assert "advance control off" in te07.message.lower()


@pytest.mark.asyncio
async def test_advance_control_off_defaults_to_expense_claim(
    db_session: AsyncSession,
) -> None:
    config = _config(_dt("DT-CLAIM", advance_control=False))
    await save_rule_book_config(db_session, config, TESTING_TENANT_UUID)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        total=Decimal("10"),
        route_target=ROUTE_TEAM,
        document_type_code="DT-CLAIM",
        email_sender=EMP_EMAIL,
        file_hash="dt-claim-auto",
    )
    # No DT pin; auto-pick is always claim (float no longer switches kinds).
    kind = await resolve_default_team_expense_kind(db_session, inv, config)
    assert kind == TEAM_EXPENSE_KIND_CLAIM
