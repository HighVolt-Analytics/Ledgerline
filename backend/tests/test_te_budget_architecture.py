"""Team Expense budget architecture: employee_email stamp, GL spend, VR-TE08."""

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
    gl_period_consumed,
    rebuild_employee_spend_cache,
)
from app.services.purchase.team_expense_validator import (
    resolve_team_expense_employee,
    run_team_expense_validations,
    vr_te06_category_cap,
    vr_te08_gl_budget,
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
        (TEAM_EXPENSE_KIND_CLAIM, "25.00", "spend@example.com", "te-arch-spend-2"),
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
async def test_gl_spend_and_retired_employee_category_cap(
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

    gl_spent = await gl_period_consumed(
        db_session,
        TESTING_TENANT_UUID,
        gl_ledger="Meals",
        period_kind="monthly",
        period_key=current_period_keys(today)["monthly"],
    )
    assert gl_spent == pytest.approx(30.0)

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
    # Employee category caps are retired — always skipped.
    retired = vr_te06_category_cap(
        emp_resp, 25.0, rule, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM, category_spent=spent
    )
    assert retired.passed and retired.skipped

    await rebuild_employee_spend_cache(db_session, TESTING_TENANT_UUID, emp, as_of=today)
    assert float(emp.mtd_spent or 0) == pytest.approx(30.0)


def test_vr_te08_skips_advances_and_blocks_over_gl_budget() -> None:
    emp = EmployeeMasterResponse(
        id="em-gl",
        name="Dana",
        email="dana@example.com",
        department="Sales",
        budget=EmployeeBudget(),
        status="Active",
        db_id=1,
    )
    skipped = vr_te08_gl_budget(
        emp,
        100.0,
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        allocated=50.0,
        consumed=0.0,
        gl_ledger="Travel",
    )
    assert skipped.passed and skipped.skipped

    no_row = vr_te08_gl_budget(
        emp, 10.0, team_expense_kind=TEAM_EXPENSE_KIND_CLAIM, allocated=None
    )
    assert no_row.passed

    fail = vr_te08_gl_budget(
        emp,
        40.0,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        allocated=100.0,
        consumed=80.0,
        gl_ledger="Travel",
        period_key="2026-08",
    )
    assert not fail.passed
    assert fail.severity == "warn"
    assert "gl budget exceeded" in fail.message.lower()
    assert "travel" in fail.message.lower()

    hard = vr_te08_gl_budget(
        emp,
        40.0,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        allocated=100.0,
        consumed=80.0,
        gl_ledger="Travel",
        period_key="2026-08",
        enforcement="hard",
    )
    assert not hard.passed
    assert hard.severity == "block"


@pytest.mark.asyncio
async def test_gl_budget_enforced_in_validation_flow(
    db_session: AsyncSession,
    capture_config,
) -> None:
    keys = current_period_keys(date.today())
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-arch-gl",
            name="GL Emp",
            email="glemp@example.com",
            spending_limits={"monthly": 5000, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Finance",
            bank={"account_number": "999999"},
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="Travel",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("20.00"),
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            employee_email="glemp@example.com",
            total=Decimal("15.00"),
            status=InvoiceStatus.PROCESSED,
            currency="SGD",
            file_hash="te-arch-gl-prior",
            team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
            invoice_date=date.today(),
            account_name="Travel",
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
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        employee_email="glemp@example.com",
        email_sender="glemp@example.com",
        total=Decimal("10.00"),
        status=InvoiceStatus.VALIDATING,
        currency="SGD",
        file_hash="te-arch-gl-claim",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        invoice_date=date.today(),
        account_name="Travel",
    )
    db_session.add(inv)
    await db_session.flush()

    results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="glemp@example.com",
        employee_email="glemp@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        config=capture_config,
        has_receipt_file=True,
        invoice=inv,
    )
    by_rule = {row.rule: row for row in results}
    assert "VR-TE08" in by_rule
    assert not by_rule["VR-TE08"].passed
    assert by_rule["VR-TE02"].passed and by_rule["VR-TE02"].skipped
    assert by_rule["VR-TE06"].passed and by_rule["VR-TE06"].skipped

    advance_results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="glemp@example.com",
        employee_email="glemp@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        config=capture_config,
        has_receipt_file=True,
        invoice=inv,
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


def test_coa_parent_child_helpers() -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry
    from app.services.master_data.chart_of_accounts_service import (
        budget_parent_for_claim_gl,
        child_ledger_names,
        parent_ledger_for_account,
    )

    coa = [
        ChartOfAccountEntry(
            code="6000",
            name="Marketing Expenses",
            type="Expense",
            sub_ledgers=[
                SubLedgerEntry(code="6001", name="Hotel"),
                SubLedgerEntry(code="6002", name="Traveling"),
            ],
        )
    ]
    assert parent_ledger_for_account("Hotel", coa) == "Marketing Expenses"
    assert parent_ledger_for_account("Marketing Expenses", coa) == "Marketing Expenses"
    names = {n.casefold() for n in child_ledger_names("Marketing Expenses", coa)}
    assert "marketing expenses" in names
    assert "hotel" in names
    assert "traveling" in names
    assert (
        budget_parent_for_claim_gl("Hotel", coa, fallback_parent="Marketing Expenses")
        == "Marketing Expenses"
    )


@pytest.mark.asyncio
async def test_parent_budget_rolls_up_child_gl_spend(
    db_session: AsyncSession,
    capture_config,
) -> None:
    from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry

    keys = current_period_keys(date.today())
    capture_config.chart_of_accounts = [
        ChartOfAccountEntry(
            code="6000",
            name="Marketing Expenses",
            type="Expense",
            sub_ledgers=[
                SubLedgerEntry(code="6001", name="Hotel"),
                SubLedgerEntry(code="6002", name="Traveling"),
            ],
        )
    ]
    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-mkt",
            name="Marketer",
            email="mkt@example.com",
            spending_limits={"monthly": 0, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Marketing",
            bank={"account_number": "111"},
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="Marketing Expenses",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("100.00"),
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            employee_email="mkt@example.com",
            total=Decimal("80.00"),
            status=InvoiceStatus.PROCESSED,
            currency="SGD",
            file_hash="te-parent-hotel-prior",
            team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
            invoice_date=date.today(),
            account_name="Hotel",
        )
    )
    await db_session.flush()

    spent = await gl_period_consumed(
        db_session,
        TESTING_TENANT_UUID,
        gl_ledger="Marketing Expenses",
        period_kind="monthly",
        period_key=keys["monthly"],
        chart_of_accounts=capture_config.chart_of_accounts,
        include_children=True,
    )
    assert spent == pytest.approx(80.0)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        employee_email="mkt@example.com",
        email_sender="mkt@example.com",
        total=Decimal("30.00"),
        status=InvoiceStatus.VALIDATING,
        currency="SGD",
        file_hash="te-parent-hotel-claim",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        invoice_date=date.today(),
        account_name="Hotel",
    )
    db_session.add(inv)
    await db_session.flush()

    data = InvoiceData(
        vendor="Hotel Co",
        total=Decimal("30.00"),
        invoice_date=date.today(),
        line_items=[],
    )
    results = await run_team_expense_validations(
        data,
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="mkt@example.com",
        employee_email="mkt@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        config=capture_config,
        has_receipt_file=True,
        invoice=inv,
    )
    by_rule = {row.rule: row for row in results}
    assert not by_rule["VR-TE08"].passed
    assert "marketing expenses" in by_rule["VR-TE08"].message.lower()


@pytest.mark.asyncio
async def test_sub_gl_budget_enforced_before_parent(
    db_session: AsyncSession,
    capture_config,
) -> None:
    """Hotel Sub-GL budget blocks even when parent wallet still has room."""
    from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry
    from app.services.master_data.chart_of_accounts_service import account_is_sub_ledger

    keys = current_period_keys(date.today())
    coa = [
        ChartOfAccountEntry(
            code="6000",
            name="Marketing Expenses",
            type="Expense",
            sub_ledgers=[
                SubLedgerEntry(code="6001", name="Hotel"),
                SubLedgerEntry(code="6002", name="Traveling"),
            ],
        )
    ]
    capture_config.chart_of_accounts = coa
    assert account_is_sub_ledger("Hotel", coa) is True
    assert account_is_sub_ledger("Marketing Expenses", coa) is False

    db_session.add(
        EmployeeMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="em-sub-bud",
            name="Sub Bud",
            email="subbud@example.com",
            spending_limits={"monthly": 0, "quarterly": 0, "annual": 0, "categories": []},
            status="Active",
            department="Marketing",
            bank={"account_number": "222"},
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="Marketing Expenses",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("1000.00"),
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="Hotel",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("50.00"),
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            route_target=ROUTE_TEAM,
            employee_email="subbud@example.com",
            total=Decimal("40.00"),
            status=InvoiceStatus.PROCESSED,
            currency="SGD",
            file_hash="te-sub-hotel-prior",
            team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
            invoice_date=date.today(),
            account_name="Hotel",
        )
    )
    await db_session.flush()

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        employee_email="subbud@example.com",
        email_sender="subbud@example.com",
        total=Decimal("20.00"),
        status=InvoiceStatus.VALIDATING,
        currency="SGD",
        file_hash="te-sub-hotel-claim",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        invoice_date=date.today(),
        account_name="Hotel",
    )
    db_session.add(inv)
    await db_session.flush()

    results = await run_team_expense_validations(
        InvoiceData(vendor="Marriott", total=Decimal("20.00"), invoice_date=date.today()),
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_TEAM,
        email_sender="subbud@example.com",
        employee_email="subbud@example.com",
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        config=capture_config,
        has_receipt_file=True,
        invoice=inv,
    )
    te08 = [row for row in results if row.rule == "VR-TE08"]
    assert any(not row.passed for row in te08)
    fail_msg = " ".join(row.message.lower() for row in te08 if not row.passed)
    assert "hotel" in fail_msg


def test_department_equals_disambiguates_team_rules() -> None:
    from app.services.rule_book.rule_engine import EvalDocument, match_team_expense_rule
    from app.schemas.rule_book_config import TeamExpenseMatchOn

    rules = [
        TeamExpenseRule(
            id="te-mkt-taxi",
            name="Marketing Traveling",
            enabled=True,
            priority=1,
            match_on=TeamExpenseMatchOn(
                description_contains="taxi",
                department_equals="Marketing",
            ),
            post_to=PostToAccounts(ledger="Marketing Expenses", sub_ledger="Traveling"),
            policy=TeamExpensePolicy(require_receipt=False),
        ),
        TeamExpenseRule(
            id="te-sales-taxi",
            name="Sales Traveling",
            enabled=True,
            priority=2,
            match_on=TeamExpenseMatchOn(
                description_contains="taxi",
                department_equals="Sales",
            ),
            post_to=PostToAccounts(ledger="Sales Expenses", sub_ledger="Traveling"),
            policy=TeamExpensePolicy(require_receipt=False),
        ),
    ]
    doc = EvalDocument(
        id="1",
        doc_number="1",
        invoice_no="1",
        vendor="Uber",
        lines=("taxi to client",),
    )
    mkt = match_team_expense_rule(
        doc, rules, amount=20.0, employee_department="Marketing"
    )
    assert mkt is not None
    assert mkt.post_to.ledger == "Marketing Expenses"

    sales = match_team_expense_rule(
        doc, rules, amount=20.0, employee_department="Sales"
    )
    assert sales is not None
    assert sales.post_to.ledger == "Sales Expenses"

    none = match_team_expense_rule(doc, rules, amount=20.0, employee_department="Ops")
    assert none is None
