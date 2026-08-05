"""Team Expense budget architecture: employee_email stamp, spend from invoices, VR-TE08."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_budget import DepartmentBudget
from app.models.employee_master import EmployeeMasterRecord
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.master_data import EmployeeBudget, EmployeeMasterResponse
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    BudgetCategoryCap,
    PostToAccounts,
    TeamExpensePolicy,
    TeamExpenseRule,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.purchase.team_expense_service import (
    record_team_expense_processed,
    stamp_team_expense_employee_identity,
)
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    employee_category_spend,
    employee_period_spend,
    rebuild_employee_spend_cache,
)
from app.services.purchase.team_expense_validator import (
    resolve_team_expense_employee,
    run_team_expense_validations,
    vr_te06_category_cap,
    vr_te08_department_budget,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_employee_email_stamp_is_permanent_against_sender_change(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-arch-1",
            name="Alice",
            email="alice@example.com",
            spending_limits={"monthly": 500, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Sales",
        )
    )
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-arch-2",
            name="Bob",
            email="bob@example.com",
            spending_limits={"monthly": 500, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Ops",
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="alice@example.com",
        status=InvoiceStatus.MAPPING,
        currency="SGD",
        file_hash="te-arch-stamp-1",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
    )
    db_session.add(inv)
    await db_session.flush()

    await stamp_team_expense_employee_identity(db_session, inv)
    assert inv.employee_email == "alice@example.com"

    inv.email_sender = "bob@example.com"
    await stamp_team_expense_employee_identity(db_session, inv)
    assert inv.employee_email == "alice@example.com"

    employees = [
        EmployeeMasterResponse(
            id="em-arch-1",
            name="Alice",
            email="alice@example.com",
            budget=EmployeeBudget(),
            status="Active",
            db_id=1,
            department="Sales",
        ),
        EmployeeMasterResponse(
            id="em-arch-2",
            name="Bob",
            email="bob@example.com",
            budget=EmployeeBudget(),
            status="Active",
            db_id=2,
            department="Ops",
        ),
    ]
    matched = resolve_team_expense_employee(
        employees,
        employee_email=inv.employee_email,
        email_sender=inv.email_sender,
    )
    assert matched is not None
    assert matched.email == "alice@example.com"


@pytest.mark.asyncio
async def test_period_spend_from_processed_invoices_excludes_advances(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    for kind, total, email, fh in (
        (TEAM_EXPENSE_KIND_CLAIM, "40.00", "spend@example.com", "te-arch-spend-1"),
        (TEAM_EXPENSE_KIND_AGAINST_ADVANCE, "25.00", "spend@example.com", "te-arch-spend-2"),
        (TEAM_EXPENSE_KIND_ADVANCE, "100.00", "spend@example.com", "te-arch-spend-3"),
        (TEAM_EXPENSE_KIND_CLAIM, "10.00", "other@example.com", "te-arch-spend-4"),
    ):
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                route_target=ROUTE_TEAM,
                employee_email=email,
                email_sender=email,
                total=Decimal(total),
                status=InvoiceStatus.PROCESSED,
                currency="SGD",
                file_hash=fh,
                team_expense_kind=kind,
                invoice_date=today,
            )
        )
    await db_session.flush()

    spend = await employee_period_spend(
        db_session, TESTING_TENANT_UUID, "spend@example.com", as_of=today
    )
    assert spend.mtd == pytest.approx(65.0)
    assert spend.ytd == pytest.approx(65.0)


@pytest.mark.asyncio
async def test_cumulative_category_limit_and_rebuild_cache(
    db_session: AsyncSession,
) -> None:
    emp = EmployeeMasterRecord(
        tenant_id=TESTING_TENANT_UUID,
        master_id="em-arch-cat",
        name="Cat Emp",
        email="cat@example.com",
        spending_limits={
            "monthly": 0,
            "quarterly": 0,
            "annual": 0,
            "categories": [{"ledger": "Meals", "cap": 50}],
        },
        status="Active",
        mtd_spent=0,
        ytd_spent=0,
    )
    db_session.add(emp)
    today = date.today()
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            employee_email="cat@example.com",
            total=Decimal("30.00"),
            status=InvoiceStatus.PROCESSED,
            currency="SGD",
            file_hash="te-arch-cat-1",
            team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
            invoice_date=today,
            account_name="Meals",
        )
    )
    await db_session.flush()

    spent = await employee_category_spend(
        db_session, TESTING_TENANT_UUID, "cat@example.com", "Meals", as_of=today
    )
    assert spent == pytest.approx(30.0)

    rule = TeamExpenseRule(
        id="te-meals",
        name="Meals",
        enabled=True,
        priority=1,
        post_to=PostToAccounts(ledger="Meals"),
        policy=TeamExpensePolicy(require_receipt=False),
    )
    emp_resp = EmployeeMasterResponse(
        id="em-arch-cat",
        name="Cat Emp",
        email="cat@example.com",
        budget=EmployeeBudget(
            categories=[BudgetCategoryCap(ledger="Meals", cap=50)],
        ),
        status="Active",
        db_id=emp.id,
    )
    ok = vr_te06_category_cap(
        emp_resp, 15.0, rule, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM, category_spent=spent
    )
    assert ok.passed
    fail = vr_te06_category_cap(
        emp_resp, 25.0, rule, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM, category_spent=spent
    )
    assert not fail.passed

    await rebuild_employee_spend_cache(db_session, TESTING_TENANT_UUID, emp, as_of=today)
    assert float(emp.mtd_spent or 0) == pytest.approx(30.0)


def test_vr_te08_skips_advances_and_blocks_over_envelope() -> None:
    emp = EmployeeMasterResponse(
        id="em-dept",
        name="Dana",
        email="dana@example.com",
        department="Sales",
        budget=EmployeeBudget(),
        status="Active",
        db_id=1,
    )
    skipped = vr_te08_department_budget(
        emp,
        100.0,
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        allocated=50.0,
        consumed=0.0,
    )
    assert skipped.passed and skipped.skipped

    no_row = vr_te08_department_budget(
        emp, 10.0, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM, allocated=None
    )
    assert no_row.passed

    fail = vr_te08_department_budget(
        emp,
        40.0,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        allocated=100.0,
        consumed=80.0,
        department="Sales",
        period_key="2026-08",
    )
    assert not fail.passed
    assert "department budget exceeded" in fail.message.lower()


@pytest.mark.asyncio
async def test_department_budget_enforced_in_validation_flow(
    db_session: AsyncSession,
    capture_config,
) -> None:
    keys = current_period_keys(date.today())
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-arch-dept",
            name="Dept Emp",
            email="deptemp@example.com",
            spending_limits={"monthly": 5000, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Finance",
            bank={"account_number": "999999"},
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="Finance",
            gl_ledger="",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("20.00"),
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            employee_email="deptemp@example.com",
            total=Decimal("15.00"),
            status=InvoiceStatus.PROCESSED,
            currency="SGD",
            file_hash="te-arch-dept-prior",
            team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
            invoice_date=date.today(),
        )
    )
    await db_session.flush()

    data = InvoiceData(
        vendor="Taxi Co",
        abn=None,
        invoice_no="TAXI-1",
        invoice_date=date.today(),
        due_date=None,
        total=Decimal("10.00"),
        line_items=[],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="deptemp@example.com",
        employee_email="deptemp@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        config=capture_config,
        has_receipt_file=True,
    )
    by_rule = {row.rule: row for row in results}
    assert "VR-TE08" in by_rule
    assert not by_rule["VR-TE08"].passed

    advance_results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="deptemp@example.com",
        employee_email="deptemp@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        config=capture_config,
        has_receipt_file=True,
    )
    assert any(
        r.rule == "VR-TE08" and r.passed and r.skipped for r in advance_results
    )


@pytest.mark.asyncio
async def test_record_processed_rebuilds_cache_not_blind_increment(
    db_session: AsyncSession,
) -> None:
    emp = EmployeeMasterRecord(
        tenant_id=TESTING_TENANT_UUID,
        master_id="em-arch-rebuild",
        name="Rebuild",
        email="rebuild@example.com",
        spending_limits={"monthly": 500, "quarterly": 0, "annual": 0, "categories": []},
        status="Active",
        mtd_spent=999.0,
        ytd_spent=999.0,
        claim_count=0,
    )
    db_session.add(emp)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        employee_email="rebuild@example.com",
        email_sender="rebuild@example.com",
        total=Decimal("12.50"),
        status=InvoiceStatus.PROCESSED,
        currency="SGD",
        file_hash="te-arch-rebuild-1",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        invoice_date=date.today(),
    )
    db_session.add(inv)
    await db_session.flush()

    await record_team_expense_processed(db_session, inv)
    assert float(emp.mtd_spent or 0) == pytest.approx(12.50)
    assert float(emp.ytd_spent or 0) == pytest.approx(12.50)
