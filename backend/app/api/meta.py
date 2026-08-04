"""Public metadata: full ISO countries and currencies for tenant setup UIs."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from fastapi import APIRouter
from pydantic import BaseModel

from app.jurisdiction.loader import get_pack_registry
from app.jurisdiction.packs import jurisdiction_api_view
from app.schemas.common import ApiEnvelope
from app.services.shared.iso_geo_catalog import (
    default_currency_for_country,
    iso3166_countries,
    list_iso4217_currency_meta,
)
from app.tenant_settings import DEFAULT_LOCALE, DEFAULT_TIMEZONE

router = APIRouter(prefix="/meta", tags=["meta"])


class CurrencyMeta(BaseModel):
    code: str
    name: str
    symbol: str
    decimal_places: int


class CountryMeta(BaseModel):
    code: str
    name: str
    default_currency: str
    tax_label: str
    statutory_tax_rate: float | None = None
    timezone: str
    locale: str
    has_jurisdiction_pack: bool = False


@lru_cache(maxsize=1)
def _currency_payload() -> tuple[CurrencyMeta, ...]:
    return tuple(
        CurrencyMeta(
            code=row["code"],
            name=row["name"],
            symbol=row["symbol"],
            decimal_places=row["decimal_places"],
        )
        for row in list_iso4217_currency_meta()
    )


@lru_cache(maxsize=1)
def _country_payload() -> tuple[CountryMeta, ...]:
    registry = get_pack_registry()
    generic = jurisdiction_api_view(registry.generic)
    rows: list[CountryMeta] = []
    for country in iso3166_countries():
        code = country["code"]
        pack = registry.packs.get(code)
        if pack is not None:
            rate = pack.statutory_tax_rate
            rows.append(
                CountryMeta(
                    code=code,
                    name=country["name"],
                    default_currency=default_currency_for_country(code),
                    tax_label=pack.tax_label,
                    statutory_tax_rate=float(rate) if rate is not None else None,
                    timezone=pack.timezone,
                    locale=pack.locale,
                    has_jurisdiction_pack=True,
                )
            )
        else:
            rows.append(
                CountryMeta(
                    code=code,
                    name=country["name"],
                    default_currency=default_currency_for_country(code),
                    tax_label=str(generic.get("tax_label") or "Tax"),
                    statutory_tax_rate=None,
                    timezone=DEFAULT_TIMEZONE,
                    locale=DEFAULT_LOCALE,
                    has_jurisdiction_pack=False,
                )
            )
    rows.sort(key=lambda r: r.name.casefold())
    return tuple(rows)


def clear_meta_catalog_cache() -> None:
    _currency_payload.cache_clear()
    _country_payload.cache_clear()


@router.get("/currencies", response_model=ApiEnvelope[list[CurrencyMeta]])
async def list_currencies() -> ApiEnvelope[list[CurrencyMeta]]:
    """All ISO 4217 books currencies."""
    # Build off the event loop — cold pycountry/Babel import is sync and multi-second.
    data = await asyncio.to_thread(lambda: list(_currency_payload()))
    return ApiEnvelope(data=data)


@router.get("/countries", response_model=ApiEnvelope[list[CountryMeta]])
async def list_countries() -> ApiEnvelope[list[CountryMeta]]:
    """All ISO 3166-1 countries with suggested default currency and tax hints."""
    data = await asyncio.to_thread(lambda: list(_country_payload()))
    return ApiEnvelope(data=data)
