"""Parent GL + Sub-GL budget tree upsert."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.department_budget import GlBudgetSubAllocation, ParentGlBudgetTreeUpsert
from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry
from app.services.master_data.department_budget_service import (
    list_department_budgets,
    upsert_parent_gl_budget_tree,
)
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
        )
    ]


@pytest.mark.asyncio
async def test_parent_tree_requires_sub_sum_equal_parent(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    with pytest.raises(ValueError, match="must equal parent budget"):
        await upsert_parent_gl_budget_tree(
            db_session,
            TESTING_TENANT_UUID,
            ParentGlBudgetTreeUpsert(
                parent_gl="Marketing Expenses",
                period_kind="monthly",
                period_key="2026-08",
                allocated=Decimal("100"),
                sub_allocations=[
                    GlBudgetSubAllocation(gl_ledger="Hotel", allocated=Decimal("40")),
                    GlBudgetSubAllocation(gl_ledger="Traveling", allocated=Decimal("50")),
                ],
            ),
        )


@pytest.mark.asyncio
async def test_parent_tree_upsert_saves_parent_and_subs(
    db_session: AsyncSession,
    capture_config,
) -> None:
    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    rows = await upsert_parent_gl_budget_tree(
        db_session,
        TESTING_TENANT_UUID,
        ParentGlBudgetTreeUpsert(
            parent_gl="Marketing Expenses",
            period_kind="monthly",
            period_key="2026-08",
            allocated=Decimal("100"),
            sub_allocations=[
                GlBudgetSubAllocation(gl_ledger="Hotel", allocated=Decimal("40")),
                GlBudgetSubAllocation(gl_ledger="Traveling", allocated=Decimal("60")),
            ],
        ),
    )
    by_gl = {row.gl_ledger: row for row in rows}
    assert set(by_gl) == {"Marketing Expenses", "Hotel", "Traveling"}
    assert by_gl["Marketing Expenses"].allocated == Decimal("100")
    assert by_gl["Hotel"].allocated == Decimal("40")
    assert by_gl["Traveling"].allocated == Decimal("60")

    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    assert len(listed) == 3

    await upsert_parent_gl_budget_tree(
        db_session,
        TESTING_TENANT_UUID,
        ParentGlBudgetTreeUpsert(
            parent_gl="Marketing Expenses",
            period_kind="monthly",
            period_key="2026-08",
            allocated=Decimal("200"),
            sub_allocations=[
                GlBudgetSubAllocation(gl_ledger="Hotel", allocated=Decimal("80")),
                GlBudgetSubAllocation(gl_ledger="Traveling", allocated=Decimal("120")),
            ],
        ),
    )
    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    assert len(listed) == 3
    hotel = next(r for r in listed if r.gl_ledger == "Hotel")
    assert hotel.allocated == Decimal("80")


@pytest.mark.asyncio
async def test_parent_tree_upsert_matches_gl_case_insensitively(
    db_session: AsyncSession,
    capture_config,
) -> None:
    """Editing with COA canonical casing must update the existing row, not insert a duplicate."""
    from app.models.department_budget import DepartmentBudget

    capture_config.chart_of_accounts = _mkt_coa()
    await save_rule_book_config(db_session, capture_config, TESTING_TENANT_UUID)

    # Legacy / differently-cased row already in DB
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="marketing expenses",
            period_kind="monthly",
            period_key="2026-07",
            allocated=Decimal("100"),
            enforcement="soft",
            notes=None,
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="hotel",
            period_kind="monthly",
            period_key="2026-07",
            allocated=Decimal("40"),
            enforcement="soft",
            notes=None,
        )
    )
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="traveling",
            period_kind="monthly",
            period_key="2026-07",
            allocated=Decimal("60"),
            enforcement="soft",
            notes=None,
        )
    )
    await db_session.flush()

    await upsert_parent_gl_budget_tree(
        db_session,
        TESTING_TENANT_UUID,
        ParentGlBudgetTreeUpsert(
            parent_gl="Marketing Expenses",
            period_kind="monthly",
            period_key="2026-07",
            allocated=Decimal("200"),
            sub_allocations=[
                GlBudgetSubAllocation(gl_ledger="Hotel", allocated=Decimal("80")),
                GlBudgetSubAllocation(gl_ledger="Traveling", allocated=Decimal("120")),
            ],
        ),
    )

    listed = await list_department_budgets(db_session, TESTING_TENANT_UUID)
    assert len(listed) == 3
    by_gl = {r.gl_ledger: r for r in listed}
    assert set(by_gl) == {"Marketing Expenses", "Hotel", "Traveling"}
    assert by_gl["Marketing Expenses"].allocated == Decimal("200")
    assert by_gl["Hotel"].allocated == Decimal("80")
    assert by_gl["Traveling"].allocated == Decimal("120")
