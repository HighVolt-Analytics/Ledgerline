"""Seed all ISO 4217 currencies into currencies catalog.

Revision ID: 085
Revises: 084
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "085"
down_revision: Union[str, None] = "084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "currencies"):
        return

    # ISO 4217 names can exceed 64 chars (e.g. XXX is 65).
    op.alter_column(
        "currencies",
        "name",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    import pycountry

    try:
        from babel.numbers import get_currency_symbol
    except Exception:  # pragma: no cover
        get_currency_symbol = None  # type: ignore[assignment]

    for currency in pycountry.currencies:
        code = str(currency.alpha_3).upper()
        name = str(getattr(currency, "name", None) or code)[:128]
        symbol = ""
        if get_currency_symbol is not None:
            try:
                symbol = get_currency_symbol(code, locale="en") or ""
                if symbol == code:
                    symbol = ""
            except Exception:
                symbol = ""
        conn.execute(
            text(
                """
                INSERT INTO currencies (code, name, symbol, decimal_places, is_active)
                VALUES (:code, :name, :symbol, 2, true)
                ON CONFLICT (code) DO UPDATE SET
                  name = EXCLUDED.name,
                  symbol = CASE
                    WHEN EXCLUDED.symbol <> '' THEN EXCLUDED.symbol
                    ELSE currencies.symbol
                  END,
                  is_active = true
                """
            ),
            {"code": code, "name": name, "symbol": symbol},
        )


def downgrade() -> None:
    # Keep seeded rows; safe no-op (cannot know which were added by 084 vs 085).
    pass
