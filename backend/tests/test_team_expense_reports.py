"""Team expense reports: advance settlement, budget utilization, expense summary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.line_item import LineItem
from app.schemas.master_data import EmployeeMasterCreate
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    BudgetCategoryCap,
    ChartOfAccountEntry,
    EmployeeBudget,
    PostingDefaults,
    RuleBookConfigPayload,
    TeamExpensePostingDefaults,
    validate_rule_book_config_payload,
)
from app.services.master_data.master_data_service import create_employee_master
from app.services.master_data.party_coa_subledger_service import party_sub_ledger_code
from app.services.reports.team_expense_reports_service import (
    build_advance_settlement_rows,
    build_budget_utilization_rows,
    build_employee_expense_summary_rows,
)
from app.services.rule_book.rule_book_config_io import (
    load_rule_book_config_dict,
    save_rule_book_config,
)
from app.services.rule_book.rule_book_mapper import ROUTE_TEAM
from app.tenant_ids import TESTING_TENANT_UUID

EMPLOYEE_ID = "em-rpt-marcus"
EMPLOYEE_EMAIL = "marcus-rpt@example.com"


def _config() -> RuleBookConfigPayload:
    return RuleBookConfigPayload(
        posting_defaults=PostingDefaults(),
        team_expense_posting=TeamExpensePostingDefaults(
            default_advance_parent_ledger="Staff Advance",
            settlement_account="Bank Account",
        ),
        chart_of_accounts=[
            ChartOfAccountEntry(code="1000", name="Bank Account", type="Asset"),
            ChartOfAccountEntry(code="1300", name="Staff Advance", type="Asset"),
            ChartOfAccountEntry(code="5000", name="Operating Expenses", type="Expense"),
            ChartOfAccountEntry(code="2000", name="Accounts Payable", type="Liability"),
        ],
    )


async def _setup_employee(
    db_session: AsyncSession,
    *,
    mtd: float = 100.0,
    qtd: float = 200.0,
    ytd: float = 500.0,
    claim_count: int = 2,
) -> None:
    await save_rule_book_config(db_session, _config(), TESTING_TENANT_UUID)
    await create_employee_master(
        db_session,
        TESTING_TENANT_UUID,
        EmployeeMasterCreate(
            master_id=EMPLOYEE_ID,
            name="Marcus Webb",
            email=EMPLOYEE_EMAIL,
            whatsapp_number="+6591110001",
            division="Ops",
            location="Singapore",
            advance_parent_ledger="Staff Advance",
            budget=EmployeeBudget(
                monthly=1000,
                quarterly=3000,
                annual=12000,
                categories=[BudgetCategoryCap(ledger="Travel", cap=400)],
            ),
            mtd_spent=mtd,
            qtd_spent=qtd,
            ytd_spent=ytd,
            claim_count=claim_count,
            last_claim="2026-05-01",
        ),
    )


@pytest.mark.asyncio
async def test_advance_settlement_ledger_pending_and_available(
    db_session: AsyncSession,
) -> None:
    await _setup_employee(db_session)
    raw = await load_rule_book_config_dict(db_session, TESTING_TENANT_UUID)
    validate_rule_book_config_payload(raw)
    code = party_sub_ledger_code(EMPLOYEE_ID)

    processed_advance = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="SGD",
        invoice_date=date(2026, 5, 1),
        total=Decimal("1000"),
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_ADVANCE,
        email_sender=EMPLOYEE_EMAIL,
        file_hash="rpt-adv-1",
    )
    db_session.add(processed_advance)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=processed_advance.id,
            date=date(2026, 5, 1),
            account_code=code,
            account_name="Marcus Webb",
            debit=Decimal("1000"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )

    against_cleared = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="SGD",
        invoice_date=date(2026, 5, 2),
        total=Decimal("400"),
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
        email_sender=EMPLOYEE_EMAIL,
        file_hash="rpt-adv-2",
    )
    db_session.add(against_cleared)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=against_cleared.id,
            date=date(2026, 5, 2),
            account_code=code,
            account_name="Marcus Webb",
            debit=Decimal("0"),
            credit=Decimal("400"),
            entry_type=EntryType.CREDIT,
        )
    )

    open_pending = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="SGD",
        invoice_date=date(2026, 5, 3),
        total=Decimal("150"),
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_AGAINST_ADVANCE,
        email_sender=EMPLOYEE_EMAIL,
        file_hash="rpt-adv-3",
    )
    db_session.add(open_pending)
    await db_session.flush()

    rows = await build_advance_settlement_rows(db_session, TESTING_TENANT_UUID)
    row = next(r for r in rows if r.employee_id == EMPLOYEE_ID)
    assert row.advance_ledger_balance == Decimal("600")
    assert row.pending_against_advance == Decimal("150")
    assert row.available_advance == Decimal("450")
    assert row.claim_ytd_spent == 500.0
    assert row.name == "Marcus Webb"


@pytest.mark.asyncio
async def test_budget_utilization_math(db_session: AsyncSession) -> None:
    await _setup_employee(db_session, mtd=250, qtd=800, ytd=4000, claim_count=5)
    rows = await build_budget_utilization_rows(db_session, TESTING_TENANT_UUID)
    row = next(r for r in rows if r.employee_id == EMPLOYEE_ID)
    assert row.budget_monthly == 1000
    assert row.mtd_spent == 250
    assert row.monthly_remaining == 750
    assert row.monthly_utilization_pct == 25.0
    assert row.quarterly_remaining == 2200
    assert row.annual_remaining == 8000
    assert "Travel:400" in row.category_caps


@pytest.mark.asyncio
async def test_expense_summary_lines_employee_and_date_filter(
    db_session: AsyncSession,
) -> None:
    await _setup_employee(db_session)

    in_range = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="SGD",
        invoice_date=date(2026, 5, 10),
        invoice_no="CLM-10",
        document_ref="DOC-10",
        total=Decimal("80"),
        account_code="5000",
        account_name="Operating Expenses",
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        document_type_code="DT-08",
        email_sender=EMPLOYEE_EMAIL,
        evaluation_status="auto_coded",
        vendor="Grab",
        file_hash="rpt-sum-1",
    )
    out_of_range = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="SGD",
        invoice_date=date(2026, 4, 1),
        invoice_no="CLM-01",
        total=Decimal("20"),
        account_code="5000",
        account_name="Operating Expenses",
        route_target=ROUTE_TEAM,
        team_expense_kind=TEAM_EXPENSE_KIND_CLAIM,
        email_sender=EMPLOYEE_EMAIL,
        file_hash="rpt-sum-2",
    )
    db_session.add_all([in_range, out_of_range])
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=in_range.id,
            description="Airport transfer",
            qty=Decimal("1"),
            amount=Decimal("80"),
            sub_ledger="Travel",
        )
    )
    await db_session.flush()

    rows = await build_employee_expense_summary_rows(
        db_session,
        TESTING_TENANT_UUID,
        date_from=date(2026, 5, 1),
        date_to=date(2026, 5, 31),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.employee_name == "Marcus Webb"
    assert row.employee_email == EMPLOYEE_EMAIL
    assert row.mobile == "+6591110001"
    assert row.division == "Ops"
    assert row.location == "Singapore"
    assert row.document_no == "DOC-10"
    assert row.line_description == "Airport transfer"
    assert row.line_amount == Decimal("80")
    assert row.ledger_code == "5000"
    assert row.ledger_name == "Travel"
    assert row.status == InvoiceStatus.PROCESSED.value
    assert row.team_expense_kind == TEAM_EXPENSE_KIND_CLAIM


@pytest.mark.asyncio
async def test_team_expense_report_apis(client: AsyncClient, db_session: AsyncSession) -> None:
    await _setup_employee(db_session)
    await db_session.flush()

    adv = await client.get("/api/reports/team-expenses/advance-settlement")
    assert adv.status_code == 200
    adv_rows = adv.json()["data"]
    assert any(r["employee_id"] == EMPLOYEE_ID for r in adv_rows)

    bud = await client.get("/api/reports/team-expenses/budget-utilization")
    assert bud.status_code == 200
    bud_rows = bud.json()["data"]
    marcus = next(r for r in bud_rows if r["employee_id"] == EMPLOYEE_ID)
    assert marcus["budget_monthly"] == 1000
    assert marcus["mtd_spent"] == 100

    summary = await client.get(
        "/api/reports/team-expenses/expense-summary?date_from=2026-01-01&date_to=2026-12-31"
    )
    assert summary.status_code == 200
    assert isinstance(summary.json()["data"], list)


@pytest.mark.asyncio
async def test_team_expense_excel_export_has_readable_headers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from openpyxl import load_workbook
    from io import BytesIO

    await _setup_employee(db_session)
    await db_session.flush()

    res = await client.get("/api/reports/team-expenses/advance-settlement/export")
    assert res.status_code == 200
    assert (
        "spreadsheetml.sheet"
        in (res.headers.get("content-type") or "")
    )
    wb = load_workbook(BytesIO(res.content))
    ws = wb.active
    # Title row 1, subtitle row 2, spacer row 3, headers row 4
    headers = [cell.value for cell in ws[4]]
    assert "Employee Name" in headers
    assert "Advance Ledger Balance" in headers
    assert "Available Advance" in headers
    assert int(res.headers.get("X-Data-Rows") or 0) >= 1

