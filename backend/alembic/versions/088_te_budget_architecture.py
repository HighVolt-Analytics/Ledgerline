"""TE architecture: employee_email, spending_limits rename, department_budgets.

Revision ID: 088
Revises: 087
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "088"
down_revision: Union[str, None] = "087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "invoices") and not _has_column(conn, "invoices", "employee_email"):
        op.add_column(
            "invoices",
            sa.Column("employee_email", sa.String(length=255), nullable=True),
        )
        op.create_index(
            "ix_invoices_employee_email",
            "invoices",
            ["employee_email"],
            unique=False,
        )

    if _has_table(conn, "employee_masters"):
        if _has_column(conn, "employee_masters", "budget") and not _has_column(
            conn, "employee_masters", "spending_limits"
        ):
            op.alter_column(
                "employee_masters",
                "budget",
                new_column_name="spending_limits",
                existing_type=sa.JSON(),
                existing_nullable=True,
            )

    if not _has_table(conn, "department_budgets"):
        op.create_table(
            "department_budgets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("department", sa.String(length=255), nullable=False),
            sa.Column("gl_ledger", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("period_kind", sa.String(length=16), nullable=False),
            sa.Column("period_key", sa.String(length=32), nullable=False),
            sa.Column("allocated", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "department",
                "gl_ledger",
                "period_kind",
                "period_key",
                name="uq_department_budget_period",
            ),
        )
        op.create_index(
            "ix_department_budgets_tenant_id",
            "department_budgets",
            ["tenant_id"],
            unique=False,
        )
        op.create_index(
            "ix_department_budgets_department",
            "department_budgets",
            ["department"],
            unique=False,
        )

    # Best-effort backfill: stamp employee_email from email_sender for Team Expenses rows.
    if _has_table(conn, "invoices") and _has_column(conn, "invoices", "employee_email"):
        conn.execute(
            text(
                """
                UPDATE invoices
                SET employee_email = LOWER(TRIM(email_sender))
                WHERE route_target = 'Team Expenses'
                  AND employee_email IS NULL
                  AND email_sender IS NOT NULL
                  AND TRIM(email_sender) <> ''
                  AND POSITION('@' IN email_sender) > 0
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, "department_budgets"):
        op.drop_table("department_budgets")

    if _has_table(conn, "employee_masters"):
        if _has_column(conn, "employee_masters", "spending_limits") and not _has_column(
            conn, "employee_masters", "budget"
        ):
            op.alter_column(
                "employee_masters",
                "spending_limits",
                new_column_name="budget",
                existing_type=sa.JSON(),
                existing_nullable=True,
            )

    if _has_table(conn, "invoices") and _has_column(conn, "invoices", "employee_email"):
        op.drop_index("ix_invoices_employee_email", table_name="invoices")
        op.drop_column("invoices", "employee_email")
