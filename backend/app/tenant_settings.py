"""Institution (tenant) locale and timezone — stored in tenant.settings_json.

Currency / timezone / locale per country come from jurisdiction pack JSON
(see ``data/jurisdiction_packs.json``). Platform DEFAULT_* constants are
SG/Singapore for schemas and empty-settings fallbacks.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.tenant import Tenant

DEFAULT_COUNTRY = "SG"
DEFAULT_TIMEZONE = "Asia/Singapore"
DEFAULT_LOCALE = "en-SG"


def _country_defaults_from_packs() -> dict[str, dict[str, str]]:
    from app.jurisdiction.loader import country_locale_map

    return country_locale_map()


def _country_currency_from_packs() -> dict[str, str]:
    from app.jurisdiction.loader import country_currency_map

    return country_currency_map()


# Populated from pack JSON at import — source of truth for currency/TZ/locale.
COUNTRY_DEFAULTS: dict[str, dict[str, str]] = _country_defaults_from_packs()
COUNTRY_CURRENCY: dict[str, str] = _country_currency_from_packs()


def refresh_country_maps_from_packs() -> None:
    """Reload COUNTRY_* maps after pack cache clear (tests / hot reload)."""
    global COUNTRY_DEFAULTS, COUNTRY_CURRENCY
    COUNTRY_DEFAULTS = _country_defaults_from_packs()
    COUNTRY_CURRENCY = _country_currency_from_packs()


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
    currencies = COUNTRY_CURRENCY
    if code in currencies:
        return currencies[code]
    return currencies.get(DEFAULT_COUNTRY, "SGD")


def tenant_currency(tenant: Tenant | None) -> str:
    return country_currency(tenant_country(tenant))


def tenant_timezone(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    tz = settings.get("timezone")
    if isinstance(tz, str) and tz.strip():
        return _validate_timezone(tz.strip())
    country = tenant_country(tenant)
    defaults = COUNTRY_DEFAULTS.get(country) or COUNTRY_DEFAULTS.get(DEFAULT_COUNTRY)
    if defaults:
        return defaults["timezone"]
    return DEFAULT_TIMEZONE


def tenant_locale(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    locale = settings.get("locale")
    if isinstance(locale, str) and locale.strip():
        return locale.strip()
    country = tenant_country(tenant)
    defaults = COUNTRY_DEFAULTS.get(country) or COUNTRY_DEFAULTS.get(DEFAULT_COUNTRY)
    if defaults:
        return defaults["locale"]
    return DEFAULT_LOCALE


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


def tenant_setup_checklist_complete(tenant: Tenant | None) -> bool:
    settings = _settings(tenant)
    return bool(settings.get("setup_checklist_complete"))


def set_setup_checklist_complete(settings_json: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(settings_json or {})
    merged["setup_checklist_complete"] = True
    return merged


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
