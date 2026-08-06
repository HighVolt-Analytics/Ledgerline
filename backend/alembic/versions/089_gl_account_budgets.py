"""TE budgets: GL-account envelopes replace department-first budgets.

Revision ID: 089
Revises: 088
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "089"
down_revision: Union[str, None] = "088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _constraint_names(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    names = {c["name"] for c in inspector.get_unique_constraints(table)}
    pk = inspector.get_pk_constraint(table)
    if pk and pk.get("name"):
        names.add(pk["name"])
    return {n for n in names if n}


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "department_budgets"):
        return

    # Drop rows that cannot map to a GL bucket.
    conn.execute(
        text(
            """
            DELETE FROM department_budgets
            WHERE TRIM(COALESCE(gl_ledger, '')) = ''
            """
        )
    )

    # Collapse duplicates that only differed by department into one GL+period row.
    # Dialect-portable: keep the highest id per (tenant, gl, period).
    dup_ids = conn.execute(
        text(
            """
            SELECT a.id
            FROM department_budgets a
            JOIN department_budgets b
              ON a.tenant_id = b.tenant_id
             AND LOWER(TRIM(a.gl_ledger)) = LOWER(TRIM(b.gl_ledger))
             AND a.period_kind = b.period_kind
             AND a.period_key = b.period_key
             AND a.id < b.id
            """
        )
    ).fetchall()
    for (row_id,) in dup_ids:
        conn.execute(
            text("DELETE FROM department_budgets WHERE id = :id"),
            {"id": row_id},
        )

    if "uq_department_budget_period" in _constraint_names(conn, "department_budgets"):
        op.drop_constraint(
            "uq_department_budget_period",
            "department_budgets",
            type_="unique",
        )

    conn.execute(
        text(
            """
            UPDATE department_budgets
            SET department = ''
            WHERE department IS NULL
            """
        )
    )
    op.alter_column(
        "department_budgets",
        "department",
        existing_type=sa.String(length=255),
        nullable=False,
        server_default="",
    )

    op.create_unique_constraint(
        "uq_gl_account_budget_period",
        "department_budgets",
        ["tenant_id", "gl_ledger", "period_kind", "period_key"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "department_budgets"):
        return

    if "uq_gl_account_budget_period" in _constraint_names(conn, "department_budgets"):
        op.drop_constraint(
            "uq_gl_account_budget_period",
            "department_budgets",
            type_="unique",
        )

    op.create_unique_constraint(
        "uq_department_budget_period",
        "department_budgets",
        ["tenant_id", "department", "gl_ledger", "period_kind", "period_key"],
    )
