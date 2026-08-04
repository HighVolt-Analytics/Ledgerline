"""Add currencies catalog and tenants.currency with country-map backfill.

Revision ID: 084
Revises: 083
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "084"
down_revision: Union[str, None] = "083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CURRENCY_SEEDS: tuple[tuple[str, str, str, int], ...] = (
    ("AUD", "Australian Dollar", "A$", 2),
    ("USD", "US Dollar", "$", 2),
    ("GBP", "British Pound", "£", 2),
    ("INR", "Indian Rupee", "₹", 2),
    ("SGD", "Singapore Dollar", "S$", 2),
    ("NZD", "New Zealand Dollar", "NZ$", 2),
    ("AED", "UAE Dirham", "د.إ", 2),
    ("EUR", "Euro", "€", 2),
)

# Same map as former COUNTRY_CURRENCY / jurisdiction packs (zero behavior change).
_COUNTRY_CURRENCY_CASE = """
CASE UPPER(COALESCE(settings_json->>'country', ''))
  WHEN 'AU' THEN 'AUD'
  WHEN 'US' THEN 'USD'
  WHEN 'GB' THEN 'GBP'
  WHEN 'IN' THEN 'INR'
  WHEN 'SG' THEN 'SGD'
  WHEN 'NZ' THEN 'NZD'
  WHEN 'AE' THEN 'AED'
  WHEN 'DE' THEN 'EUR'
  ELSE 'SGD'
END
"""


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, "currencies"):
        op.create_table(
            "currencies",
            sa.Column("code", sa.String(length=3), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("symbol", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("decimal_places", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.PrimaryKeyConstraint("code"),
        )

    for code, name, symbol, decimals in _CURRENCY_SEEDS:
        conn.execute(
            text(
                """
                INSERT INTO currencies (code, name, symbol, decimal_places, is_active)
                VALUES (:code, :name, :symbol, :decimals, true)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "name": name, "symbol": symbol, "decimals": decimals},
        )

    if _has_table(conn, "tenants") and not _has_column(conn, "tenants", "currency"):
        op.add_column(
            "tenants",
            sa.Column(
                "currency",
                sa.String(length=3),
                nullable=False,
                server_default="SGD",
            ),
        )
        conn.execute(
            text(f"UPDATE tenants SET currency = {_COUNTRY_CURRENCY_CASE}")
        )
        op.create_foreign_key(
            "fk_tenants_currency_code",
            "tenants",
            "currencies",
            ["currency"],
            ["code"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, "tenants") and _has_column(conn, "tenants", "currency"):
        op.drop_constraint("fk_tenants_currency_code", "tenants", type_="foreignkey")
        op.drop_column("tenants", "currency")
    if _has_table(conn, "currencies"):
        op.drop_table("currencies")
