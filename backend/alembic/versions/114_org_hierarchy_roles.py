"""Rename privilege-matrix tenant roles to org hierarchy labels.

Maps membership/invite slugs:
  user → employee
  functional_manager → manager
  functional_supervisor → department_head
  finance_head → finance_manager
  bookkeeper → cfo
  auditor → director

Revision ID: 114
Revises: 113
"""

from typing import Sequence, Union

from alembic import op

revision: str = "114"
down_revision: Union[str, None] = "113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_MAP: tuple[tuple[str, str], ...] = (
    ("user", "employee"),
    ("functional_manager", "manager"),
    ("functional_supervisor", "department_head"),
    ("finance_head", "finance_manager"),
    ("bookkeeper", "cfo"),
    ("auditor", "director"),
)

_TABLES: tuple[str, ...] = ("user_tenant_mappings", "tenant_member_invites")


def upgrade() -> None:
    for table in _TABLES:
        for old, new in _ROLE_MAP:
            op.execute(
                f"""
                UPDATE {table}
                SET role = '{new}'
                WHERE role = '{old}'
                """
            )


def downgrade() -> None:
    for table in _TABLES:
        for old, new in _ROLE_MAP:
            op.execute(
                f"""
                UPDATE {table}
                SET role = '{old}'
                WHERE role = '{new}'
                """
            )
