"""Institution timezone helpers and independent books currency."""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.jurisdiction.packs import tenant_jurisdiction
from app.models.tenant import Tenant
from app.tenant_settings import (
    UnsupportedCurrencyError,
    country_currency,
    default_institution_settings,
    institution_settings_view,
    merge_institution_settings,
    resolve_books_currency,
    tenant_currency,
    tenant_custom_bundle_field_key,
    tenant_today,
    tenant_timezone,
    validate_currency_code,
)


def test_default_institution_settings():
    assert default_institution_settings()["timezone"] == "Asia/Singapore"
    assert default_institution_settings()["country"] == "SG"


def test_tenant_timezone_from_country():
    tenant = Tenant(
        name="US Co",
        slug="us-co",
        currency="USD",
        settings_json={"country": "US"},
    )
    assert tenant_timezone(tenant) == "America/New_York"


def test_tenant_timezone_explicit_override():
    tenant = Tenant(
        name="US West",
        slug="us-west",
        currency="USD",
        settings_json={"country": "US", "timezone": "America/Los_Angeles"},
    )
    assert tenant_timezone(tenant) == "America/Los_Angeles"


def test_merge_institution_settings_country_sets_timezone():
    merged = merge_institution_settings(None, country="GB")
    assert merged["country"] == "GB"
    assert merged["timezone"] == "Europe/London"
    assert merged["locale"] == "en-GB"
    assert "currency" not in merged


def test_institution_settings_view_defaults_without_json():
    tenant = Tenant(name="Acme", slug="acme", currency="SGD")
    view = institution_settings_view(tenant)
    assert view["country"] == "SG"
    assert view["timezone"] == "Asia/Singapore"
    assert view["locale"] == "en-SG"
    assert view["currency"] == "SGD"


def test_tenant_today_uses_institution_zone():
    tenant = Tenant(
        name="Acme",
        slug="acme",
        currency="NZD",
        settings_json={"timezone": "Pacific/Auckland"},
    )
    from datetime import datetime as real_dt

    class FakeDatetime:
        @classmethod
        def now(cls, tz):
            assert str(tz) == "Pacific/Auckland"
            return real_dt(2026, 6, 23, 10, 0, tzinfo=tz)

    with patch("app.tenant_settings.datetime", FakeDatetime):
        assert tenant_today(tenant) == date(2026, 6, 23)


@pytest.mark.parametrize(
    ("country", "currency"),
    [
        ("AU", "AUD"),
        ("US", "USD"),
        ("GB", "GBP"),
        ("IN", "INR"),
        ("SG", "SGD"),
        ("NZ", "NZD"),
        ("AE", "AED"),
        ("DE", "EUR"),
    ],
)
def test_country_currency_mapping(country: str, currency: str) -> None:
    assert country_currency(country) == currency


def test_country_currency_unknown_defaults_to_sg() -> None:
    assert country_currency("XX") == "SGD"


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("AU", "AUD"),
        ("US", "USD"),
        ("GB", "GBP"),
        ("IN", "INR"),
        ("SG", "SGD"),
        ("NZ", "NZD"),
        ("AE", "AED"),
        ("DE", "EUR"),
    ],
)
def test_resolve_books_currency_defaults_match_legacy_pairs(country: str, expected: str) -> None:
    assert resolve_books_currency(country, None) == expected


def test_resolve_books_currency_explicit_override() -> None:
    assert resolve_books_currency("IN", "USD") == "USD"


def test_validate_currency_code_rejects_unknown() -> None:
    with pytest.raises(UnsupportedCurrencyError):
        validate_currency_code("ZZZ")


def test_tenant_currency_reads_column_not_country() -> None:
    tenant = Tenant(
        name="IN USD Co",
        slug="in-usd",
        currency="USD",
        settings_json={"country": "IN"},
    )
    assert tenant_currency(tenant) == "USD"
    pack = tenant_jurisdiction(tenant)
    assert pack.tax_label == "GST"
    assert pack.statutory_tax_rate == Decimal("18")


def test_tenant_currency_falls_back_when_column_blank() -> None:
    tenant = Tenant(name="SG Co", slug="sg-co", settings_json={"country": "SG"})
    tenant.currency = ""  # type: ignore[assignment]
    assert tenant_currency(tenant) == "SGD"


def test_institution_settings_view_includes_currency() -> None:
    tenant = Tenant(
        name="IN Co",
        slug="in-co",
        currency="INR",
        settings_json={"country": "IN"},
    )
    view = institution_settings_view(tenant)
    assert view["currency"] == "INR"
    assert view["custom_bundle_field_key"] == ""


def test_custom_bundle_field_key_roundtrip() -> None:
    merged = merge_institution_settings(
        {"country": "AU"},
        custom_bundle_field_key="other_reference",
    )
    assert merged["custom_bundle_field_key"] == "other_reference"
    tenant = Tenant(name="AU Co", slug="au-co", currency="AUD", settings_json=merged)
    assert tenant_custom_bundle_field_key(tenant) == "other_reference"
    cleared = merge_institution_settings(merged, custom_bundle_field_key="")
    assert "custom_bundle_field_key" not in cleared
    assert (
        tenant_custom_bundle_field_key(
            Tenant(name="X", slug="x", currency="SGD", settings_json=cleared)
        )
        is None
    )
