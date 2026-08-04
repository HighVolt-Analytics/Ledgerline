"""Ensure currency rows exist for tenants.currency FK (ISO 4217)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.currency import Currency
from app.services.shared.iso4217_catalog import is_iso4217_currency
from app.services.shared.iso_geo_catalog import list_iso4217_currency_meta
from app.tenant_settings import UnsupportedCurrencyError, validate_currency_code


async def ensure_currency_row(session: AsyncSession, code: str) -> str:
    """Insert currency catalog row if missing; return validated ISO code."""
    token = validate_currency_code(code)
    existing = await session.get(Currency, token)
    if existing is not None:
        return token

    meta = next((row for row in list_iso4217_currency_meta() if row["code"] == token), None)
    session.add(
        Currency(
            code=token,
            name=(meta["name"] if meta else token),
            symbol=(meta["symbol"] if meta else ""),
            decimal_places=(meta["decimal_places"] if meta else 2),
            is_active=True,
        )
    )
    await session.flush()
    return token


async def ensure_currency_row_if_iso(session: AsyncSession, code: str | None) -> str | None:
    if code is None or not str(code).strip():
        return None
    if not is_iso4217_currency(code):
        raise UnsupportedCurrencyError(f"Unsupported currency: {code!r}")
    return await ensure_currency_row(session, code)
