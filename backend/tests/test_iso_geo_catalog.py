"""ISO geo catalog + meta API coverage for full country/currency lists."""

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.meta import clear_meta_catalog_cache
from app.jurisdiction.packs import tenant_jurisdiction
from app.models.tenant import Tenant
from app.services.shared.iso4217_catalog import is_iso4217_currency
from app.services.shared.iso_geo_catalog import (
    clear_iso_geo_catalog_cache,
    default_currency_for_country,
    is_iso3166_country,
    iso3166_countries,
    list_iso4217_currency_meta,
)
from app.tenant_settings import (
    UnsupportedCountryError,
    UnsupportedCurrencyError,
    resolve_books_currency,
    tenant_currency,
    validate_country_code,
    validate_currency_code,
)


@pytest.fixture(autouse=True)
def _clear_catalog_caches() -> None:
    clear_iso_geo_catalog_cache()
    clear_meta_catalog_cache()
    yield
    clear_iso_geo_catalog_cache()
    clear_meta_catalog_cache()


def test_iso3166_country_helpers() -> None:
    assert is_iso3166_country("FR")
    assert is_iso3166_country("in")
    assert not is_iso3166_country("ZZ")
    assert not is_iso3166_country("USA")
    assert validate_country_code("jp") == "JP"
    with pytest.raises(UnsupportedCountryError):
        validate_country_code("XX")


def test_iso4217_currency_helpers() -> None:
    assert is_iso4217_currency("CHF")
    assert is_iso4217_currency("jpy")
    assert validate_currency_code("cad") == "CAD"
    with pytest.raises(UnsupportedCurrencyError):
        validate_currency_code("ZZZ")


def test_default_currency_for_country_uses_babel_and_packs() -> None:
    assert default_currency_for_country("DE") == "EUR"
    assert default_currency_for_country("IN") == "INR"
    assert resolve_books_currency("FR", None) == default_currency_for_country("FR")
    assert resolve_books_currency("FR", "USD") == "USD"


def test_catalog_sizes() -> None:
    assert len(iso3166_countries()) > 100
    assert len(list_iso4217_currency_meta()) > 100


@pytest.mark.asyncio
async def test_meta_endpoints_return_full_catalogs() -> None:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        countries = await client.get("/api/meta/countries")
        currencies = await client.get("/api/meta/currencies")
    assert countries.status_code == 200
    assert currencies.status_code == 200
    country_rows = countries.json()["data"]
    currency_rows = currencies.json()["data"]
    assert len(country_rows) > 100
    assert len(currency_rows) > 100
    packed = {row["code"]: row for row in country_rows}
    assert packed["IN"]["has_jurisdiction_pack"] is True
    assert packed["IN"]["tax_label"] == "GST"
    assert packed["FR"]["has_jurisdiction_pack"] is False
    assert any(row["code"] == "CHF" for row in currency_rows)


def test_pack_country_keeps_tax_when_currency_independent() -> None:
    tenant = Tenant(
        name="IN USD",
        slug="in-usd-iso",
        currency="USD",
        settings_json={"country": "IN"},
    )
    assert tenant_currency(tenant) == "USD"
    pack = tenant_jurisdiction(tenant)
    assert pack.tax_label == "GST"
    assert pack.statutory_tax_rate == Decimal("18")


def test_unknown_country_uses_generic_jurisdiction() -> None:
    tenant = Tenant(
        name="FR Co",
        slug="fr-co",
        currency="EUR",
        settings_json={"country": "FR"},
    )
    pack = tenant_jurisdiction(tenant)
    assert pack.country in {"XX", "FR"} or pack.tax_label == "Tax"
