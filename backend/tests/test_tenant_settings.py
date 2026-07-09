"""Institution timezone helpers."""

import pytest
from datetime import date
from unittest.mock import patch

from app.models.tenant import Tenant
from app.tenant_settings import (
    country_currency,
    default_institution_settings,
    institution_settings_view,
    merge_institution_settings,
    tenant_currency,
    tenant_today,
    tenant_timezone,
)


def test_default_institution_settings():
    assert default_institution_settings()["timezone"] == "Asia/Singapore"
    assert default_institution_settings()["country"] == "SG"


def test_tenant_timezone_from_country():
    tenant = Tenant(
        name="US Co",
        slug="us-co",
        settings_json={"country": "US"},
    )
    assert tenant_timezone(tenant) == "America/New_York"


def test_tenant_timezone_explicit_override():
    tenant = Tenant(
        name="US West",
        slug="us-west",
        settings_json={"country": "US", "timezone": "America/Los_Angeles"},
    )
    assert tenant_timezone(tenant) == "America/Los_Angeles"


def test_merge_institution_settings_country_sets_timezone():
    merged = merge_institution_settings(None, country="GB")
    assert merged["country"] == "GB"
    assert merged["timezone"] == "Europe/London"
    assert merged["locale"] == "en-GB"


def test_institution_settings_view_defaults_without_json():
    tenant = Tenant(name="Acme", slug="acme")
    view = institution_settings_view(tenant)
    assert view["country"] == "SG"
    assert view["timezone"] == "Asia/Singapore"
    assert view["locale"] == "en-SG"
    assert view["currency"] == "SGD"


def test_tenant_today_uses_institution_zone():
    tenant = Tenant(name="Acme", slug="acme", settings_json={"timezone": "Pacific/Auckland"})
    from datetime import datetime as real_dt
    from zoneinfo import ZoneInfo

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


def test_tenant_currency_from_country() -> None:
    tenant = Tenant(name="SG Co", slug="sg-co", settings_json={"country": "SG"})
    assert tenant_currency(tenant) == "SGD"


def test_institution_settings_view_includes_currency() -> None:
    tenant = Tenant(name="IN Co", slug="in-co", settings_json={"country": "IN"})
    view = institution_settings_view(tenant)
    assert view["currency"] == "INR"
