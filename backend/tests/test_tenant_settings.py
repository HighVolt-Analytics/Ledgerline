"""Institution timezone helpers."""

from datetime import date
from unittest.mock import patch

from app.models.tenant import Tenant
from app.tenant_settings import (
    default_institution_settings,
    institution_settings_view,
    merge_institution_settings,
    tenant_today,
    tenant_timezone,
)


def test_default_institution_settings():
    assert default_institution_settings()["timezone"] == "Australia/Sydney"


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
    assert view["country"] == "AU"
    assert view["timezone"] == "Australia/Sydney"


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
