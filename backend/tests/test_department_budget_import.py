"""GL budget bulk import from spreadsheet templates."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry
from app.services.master_data.department_budget_import_service import (
    build_budget_import_template,
    import_department_budgets,
    parse_budget_import_file,
)
from app.services.master_data.department_budget_service import list_department_budgets
from app.services.rule_book.rule_book_config_io import save_rule_book_config
from app.tenant_ids import TESTING_TENANT_UUID


def _mkt_coa() -> list[ChartOfAccountEntry]:
    return [
        ChartOfAccountEntry(
            code="6000",
            name="Marketing Expenses",
            type="Expense",
            sub_ledgers=[
                SubLedgerEntry(code="01", name="Hotel"),
                SubLedgerEntry(code="02", name="Traveling"),
            ],
        ),
        ChartOfAccountEntry(
            code="6100",
            name="Office Supplies",
            type="Expense",
            sub_ledgers=[],
        ),
        ChartOfAccountEntry(
            code="1200",
            name="Staff Advances",
            type="Asset",
            sub_ledgers=[],
        ),
    ]


def _budget_csv(rows: list[list[str]]) -> bytes:
    lines = [
        "parent_gl,gl_ledger,period_kind,period_key,allocated,enforcement,notes"
    ]
    for row in rows:
        lines.append(",".join(row))
    return "\n".join(lines).encode("utf-8")


def _budget_xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "GL budgets"
    sheet.append([])
    sheet.append([])
    sheet.append(
        [
            "Parent GL *",
            "GL ledger *",
            "Period kind *",
            "Period key *",
            "Allocated *",
            "Enforcement",
            "Notes",
        ]
    )
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_parse_budget_csv_aliases() -> None:
    data = (
        "Parent GL,GL Account,Period Kind,Period,Budget,Over Budget\n"
        "Marketing Expenses,Marketing Expenses,monthly,2026-08,10000,soft\n"
        "Marketing Expenses,Hotel,monthly,2026-08,4000,\n"
        "Marketing Expenses,Traveling,monthly,2026-08,6000,\n"
    ).encode("utf-8")
    rows = parse_budget_import_file(data, "budgets.csv")
    assert len(rows) == 3
    assert rows[0]["Parent GL"] == "Marketing Expenses"
    assert rows[0]["Budget"] == "10000"


@pytest.mark.asyncio
async def test_template_prefills_expense_coa(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    content = await build_budget_import_template(
        db_session,
        TESTING_TENANT_UUID,
        period_kind="monthly",
        period_key="2026-08",
        prefill_coa=True,
    )
    workbook = load_workbook(io.BytesIO(content))
    assert "Budget data" in workbook.sheetnames
    assert "Instructions" in workbook.sheetnames
    sheet = workbook["Budget data"]
    values = [
        [cell.value for cell in row]
        for row in sheet.iter_rows(min_row=5, max_row=10, values_only=False)
    ]
    # Parent + 2 subs for Marketing, then Office Supplies parent
    gl_pairs = [(row[0], row[1]) for row in values if row[0]]
    assert ("Marketing Expenses", "Marketing Expenses") in gl_pairs
    assert ("Marketing Expenses", "Hotel") in gl_pairs
    assert ("Marketing Expenses", "Traveling") in gl_pairs
    assert ("Office Supplies", "Office Supplies") in gl_pairs
    assert ("Staff Advances", "Staff Advances") in gl_pairs


@pytest.mark.asyncio
async def test_import_creates_parent_tree(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    csv_bytes = _budget_csv(
        [
            [
                "Marketing Expenses",
                "Marketing Expenses",
                "monthly",
                "2026-08",
                "100",
                "hard",
                "Launch",
            ],
            ["Marketing Expenses", "Hotel", "monthly", "2026-08", "40", "", ""],
            ["Marketing Expenses", "Traveling", "monthly", "2026-08", "60", "", ""],
            [
                "Office Supplies",
                "Office Supplies",
                "monthly",
                "2026-08",
                "250",
                "soft",
                "",
            ],
        ]
    )
    rows = parse_budget_import_file(csv_bytes, "budgets.csv")
    dry = await import_department_budgets(
        db_session, TESTING_TENANT_UUID, rows=rows, dry_run=True
    )
    assert dry.created == 2
    assert dry.updated == 0
    assert dry.errors == []

    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    assert listed == []

    result = await import_department_budgets(
        db_session, TESTING_TENANT_UUID, rows=rows, dry_run=False
    )
    assert result.created == 2
    assert result.updated == 0
    assert result.errors == []

    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    by_gl = {row.gl_ledger: row for row in listed}
    assert by_gl["Marketing Expenses"].allocated == Decimal("100")
    assert by_gl["Marketing Expenses"].enforcement == "hard"
    assert by_gl["Hotel"].allocated == Decimal("40")
    assert by_gl["Traveling"].allocated == Decimal("60")
    assert by_gl["Office Supplies"].allocated == Decimal("250")


@pytest.mark.asyncio
async def test_import_rejects_sub_sum_mismatch(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    rows = parse_budget_import_file(
        _budget_xlsx(
            [
                ["Marketing Expenses", "Marketing Expenses", "monthly", "2026-08", 100, "soft", ""],
                ["Marketing Expenses", "Hotel", "monthly", "2026-08", 40, "", ""],
                ["Marketing Expenses", "Traveling", "monthly", "2026-08", 50, "", ""],
            ]
        ),
        "budgets.xlsx",
    )
    result = await import_department_budgets(
        db_session, TESTING_TENANT_UUID, rows=rows, dry_run=False
    )
    assert result.created == 0
    assert result.errors
    assert any("must equal parent budget" in err.message for err in result.errors)


@pytest.mark.asyncio
async def test_import_updates_existing_and_skips_blank_groups(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    first = parse_budget_import_file(
        _budget_csv(
            [
                [
                    "Marketing Expenses",
                    "Marketing Expenses",
                    "monthly",
                    "2026-08",
                    "100",
                    "soft",
                    "",
                ],
                ["Marketing Expenses", "Hotel", "monthly", "2026-08", "40", "", ""],
                ["Marketing Expenses", "Traveling", "monthly", "2026-08", "60", "", ""],
            ]
        ),
        "budgets.csv",
    )
    await import_department_budgets(
        db_session, TESTING_TENANT_UUID, rows=first, dry_run=False
    )

    second = parse_budget_import_file(
        _budget_csv(
            [
                [
                    "Marketing Expenses",
                    "Marketing Expenses",
                    "monthly",
                    "2026-08",
                    "200",
                    "hard",
                    "raised",
                ],
                ["Marketing Expenses", "Hotel", "monthly", "2026-08", "80", "", ""],
                ["Marketing Expenses", "Traveling", "monthly", "2026-08", "120", "", ""],
                [
                    "Office Supplies",
                    "Office Supplies",
                    "monthly",
                    "2026-08",
                    "",
                    "soft",
                    "",
                ],
            ]
        ),
        "budgets.csv",
    )
    result = await import_department_budgets(
        db_session, TESTING_TENANT_UUID, rows=second, dry_run=False
    )
    assert result.updated == 1
    assert result.created == 0
    assert any(p.action == "skip" for p in result.previews)

    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    mkt = next(row for row in listed if row.gl_ledger == "Marketing Expenses")
    assert mkt.allocated == Decimal("200")
    assert mkt.enforcement == "hard"
    assert mkt.notes == "raised"
    assert not any(row.gl_ledger == "Office Supplies" for row in listed)
