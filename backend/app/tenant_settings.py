"""Institution (tenant) locale and timezone — stored in tenant.settings_json."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.tenant import Tenant

DEFAULT_COUNTRY = "SG"
DEFAULT_TIMEZONE = "Asia/Singapore"
DEFAULT_LOCALE = "en-SG"

# Primary business timezone per supported country (institution default).
COUNTRY_DEFAULTS: dict[str, dict[str, str]] = {
    "AU": {"timezone": "Australia/Sydney", "locale": "en-AU"},
    "US": {"timezone": "America/New_York", "locale": "en-US"},
    "GB": {"timezone": "Europe/London", "locale": "en-GB"},
    "IN": {"timezone": "Asia/Kolkata", "locale": "en-IN"},
    "SG": {"timezone": "Asia/Singapore", "locale": "en-SG"},
    "NZ": {"timezone": "Pacific/Auckland", "locale": "en-NZ"},
    "AE": {"timezone": "Asia/Dubai", "locale": "ar-AE"},
    "DE": {"timezone": "Europe/Berlin", "locale": "de-DE"},
}

# ISO currency per supported country — aligned with frontend settingsData.ts.
COUNTRY_CURRENCY: dict[str, str] = {
    "AU": "AUD",
    "US": "USD",
    "GB": "GBP",
    "IN": "INR",
    "SG": "SGD",
    "NZ": "NZD",
    "AE": "AED",
    "DE": "EUR",
}


def default_institution_settings() -> dict[str, str]:
    return {
        "country": DEFAULT_COUNTRY,
        "timezone": DEFAULT_TIMEZONE,
        "locale": DEFAULT_LOCALE,
    }


def _settings(tenant: Tenant | None) -> dict[str, Any]:
    raw = tenant.settings_json if tenant else None
    return raw if isinstance(raw, dict) else {}


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE
    return value


def tenant_country(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    country = settings.get("country")
    if isinstance(country, str) and country.strip():
        return country.strip().upper()
    return DEFAULT_COUNTRY


def country_currency(country_code: str) -> str:
    code = (country_code or "").strip().upper()
    return COUNTRY_CURRENCY.get(code, COUNTRY_CURRENCY[DEFAULT_COUNTRY])


def tenant_currency(tenant: Tenant | None) -> str:
    return country_currency(tenant_country(tenant))


def tenant_timezone(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    tz = settings.get("timezone")
    if isinstance(tz, str) and tz.strip():
        return _validate_timezone(tz.strip())
    country = tenant_country(tenant)
    return COUNTRY_DEFAULTS.get(country, COUNTRY_DEFAULTS[DEFAULT_COUNTRY])["timezone"]


def tenant_locale(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    locale = settings.get("locale")
    if isinstance(locale, str) and locale.strip():
        return locale.strip()
    country = tenant_country(tenant)
    return COUNTRY_DEFAULTS.get(country, COUNTRY_DEFAULTS[DEFAULT_COUNTRY])["locale"]


def tenant_today(tenant: Tenant | None) -> date:
    """Calendar 'today' for the institution — use instead of date.today()."""
    return datetime.now(ZoneInfo(tenant_timezone(tenant))).date()


def institution_settings_view(tenant: Tenant | None) -> dict[str, str]:
    return {
        "country": tenant_country(tenant),
        "timezone": tenant_timezone(tenant),
        "locale": tenant_locale(tenant),
        "currency": tenant_currency(tenant),
    }


def tenant_industry(tenant: Tenant | None) -> str | None:
    settings = _settings(tenant)
    industry = settings.get("industry")
    if isinstance(industry, str) and industry.strip():
        return industry.strip()
    return None


def tenant_onboarding_completed(tenant: Tenant | None) -> bool:
    settings = _settings(tenant)
    if "onboarding_completed" not in settings:
        return True
    return bool(settings.get("onboarding_completed"))


def build_tenant_settings(
    *,
    country: str = DEFAULT_COUNTRY,
    industry: str | None = None,
    onboarding_completed: bool = False,
) -> dict[str, Any]:
    """Initial settings_json for a new client tenant."""
    settings = merge_institution_settings(None, country=country)
    if industry:
        settings["industry"] = industry.strip()
    settings["onboarding_completed"] = onboarding_completed
    return settings


def merge_institution_settings(
    current: dict[str, Any] | None,
    *,
    country: str | None = None,
    timezone: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    """Apply institution profile updates to settings_json."""
    out: dict[str, Any] = dict(current or {})

    if country is not None:
        code = country.strip().upper()
        out["country"] = code
        defaults = COUNTRY_DEFAULTS.get(code)
        if defaults:
            # Country change resets derived locale unless caller overrides both.
            if timezone is None:
                out["timezone"] = defaults["timezone"]
            if locale is None:
                out["locale"] = defaults["locale"]

    if timezone is not None:
        out["timezone"] = _validate_timezone(timezone.strip())
    if locale is not None:
        out["locale"] = locale.strip()

    return out


def merge_onboarding_settings(
    current: dict[str, Any] | None,
    *,
    industry: str | None = None,
    onboarding_completed: bool | None = None,
) -> dict[str, Any]:
    """Apply onboarding profile updates to settings_json."""
    out: dict[str, Any] = dict(current or {})
    if industry is not None:
        out["industry"] = industry.strip() or None
    if onboarding_completed is not None:
        out["onboarding_completed"] = onboarding_completed
    return out


def tenant_payment_execution_disabled(tenant: Tenant | None) -> bool:
    """Per-tenant emergency disable for payment instruction / mark-paid orchestration."""
    settings = _settings(tenant)
    return bool(settings.get("payment_execution_disabled"))
