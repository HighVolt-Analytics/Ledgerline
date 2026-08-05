"""Institution (tenant) locale and timezone — stored in tenant.settings_json.

Currency / timezone / locale *suggestions* per country come from jurisdiction pack JSON
(see ``data/jurisdiction_packs.json``) and ISO catalogs. Books currency is stored on
``tenants.currency`` and is independent of country (tax jurisdiction). Platform
DEFAULT_* constants are SG/Singapore for schemas and empty-settings fallbacks.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.tenant import Tenant

DEFAULT_COUNTRY = "SG"
DEFAULT_TIMEZONE = "Asia/Singapore"
DEFAULT_LOCALE = "en-SG"
DEFAULT_CURRENCY = "SGD"


class UnsupportedCurrencyError(ValueError):
    """Raised when a currency code is not a valid ISO 4217 code."""


class UnsupportedCountryError(ValueError):
    """Raised when a country code is not a valid ISO 3166-1 alpha-2 code."""


def _country_defaults_from_packs() -> dict[str, dict[str, str]]:
    from app.jurisdiction.loader import country_locale_map

    return country_locale_map()


def _country_currency_from_packs() -> dict[str, str]:
    from app.jurisdiction.loader import country_currency_map

    return country_currency_map()


# Pack-backed maps (rich tax jurisdictions). Full ISO defaults use iso_geo_catalog.
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
    """Suggested default books currency for a country (not an enforced mapping)."""
    from app.services.shared.iso_geo_catalog import default_currency_for_country

    return default_currency_for_country(country_code)


def validate_country_code(code: str | None) -> str:
    """Normalize and whitelist against ISO 3166-1 alpha-2."""
    from app.services.shared.iso_geo_catalog import is_iso3166_country

    token = (code or "").strip().upper()
    if not is_iso3166_country(token):
        raise UnsupportedCountryError(f"Unsupported country: {code!r}")
    return token


def validate_currency_code(code: str | None) -> str:
    """Normalize and whitelist against ISO 4217 (pycountry)."""
    from app.services.shared.iso4217_catalog import is_iso4217_currency

    token = (code or "").strip().upper()
    if not is_iso4217_currency(token):
        raise UnsupportedCurrencyError(f"Unsupported currency: {code!r}")
    return token


def resolve_books_currency(country: str, currency: str | None = None) -> str:
    """Resolve books currency for create/update.

    Explicit ``currency`` wins (after validation). If omitted, use the country's
    suggested default for backward compatibility with older clients.
    """
    if currency is not None and str(currency).strip():
        return validate_currency_code(currency)
    return country_currency(country)


def tenant_currency(tenant: Tenant | None) -> str:
    """Tenant books / reporting currency from ``tenants.currency`` (column)."""
    if tenant is not None:
        raw = getattr(tenant, "currency", None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().upper()
    return country_currency(tenant_country(tenant))


def tenant_timezone(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    tz = settings.get("timezone")
    if isinstance(tz, str) and tz.strip():
        return _validate_timezone(tz.strip())
    return country_timezone_suggestion(tenant_country(tenant))


def tenant_locale(tenant: Tenant | None) -> str:
    settings = _settings(tenant)
    locale = settings.get("locale")
    if isinstance(locale, str) and locale.strip():
        return locale.strip()
    return country_locale_suggestion(tenant_country(tenant))


def tenant_today(tenant: Tenant | None) -> date:
    """Calendar 'today' for the institution — use instead of date.today()."""
    return datetime.now(ZoneInfo(tenant_timezone(tenant))).date()


def tenant_date_order(tenant: Tenant | None) -> str:
    """Parse order for ambiguous numeric dates (finance locale)."""
    country = tenant_country(tenant)
    if country in {"US", "PH", "CA", "BZ", "FM", "MH", "PW"}:
        return "MDY"
    if country in {"JP", "CN", "KR", "TW", "HU", "LT"}:
        return "YMD"
    return "DMY"


def tenant_custom_bundle_field_key(tenant: Tenant | None) -> str | None:
    """Optional extracted_fields key used as last-resort vision bundle linkage.

    Empty / unset → step skipped. Typical value: ``other_reference``.
    """
    settings = _settings(tenant)
    raw = settings.get("custom_bundle_field_key")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def institution_settings_view(tenant: Tenant | None) -> dict[str, str]:
    custom = tenant_custom_bundle_field_key(tenant)
    return {
        "country": tenant_country(tenant),
        "timezone": tenant_timezone(tenant),
        "locale": tenant_locale(tenant),
        "currency": tenant_currency(tenant),
        "custom_bundle_field_key": custom or "",
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
    currency: str | None = None,
) -> dict[str, Any]:
    """Initial settings_json for a new client tenant.

    ``currency`` is accepted for API symmetry but is *not* stored in settings_json;
    callers must set ``tenant.currency`` via :func:`resolve_books_currency`.
    """
    _ = currency  # resolved at call sites onto tenants.currency
    settings = merge_institution_settings(None, country=country)
    if industry:
        settings["industry"] = industry.strip()
    settings["onboarding_completed"] = onboarding_completed
    return settings


def country_timezone_suggestion(country_code: str) -> str:
    """Timezone for a country: jurisdiction pack → CLDR primary → platform default.

    Platform default (Asia/Singapore) is only used when the country is unknown /
    has no CLDR territory zones — never as a substitute for a known country.
    """
    code = (country_code or "").strip().upper()
    defaults = COUNTRY_DEFAULTS.get(code)
    if defaults and defaults.get("timezone"):
        return defaults["timezone"]
    from app.services.shared.iso_geo_catalog import default_timezone_for_country

    resolved = default_timezone_for_country(code)
    if resolved:
        return resolved
    return DEFAULT_TIMEZONE


def country_locale_suggestion(country_code: str) -> str:
    """Locale for a country: jurisdiction pack → Babel → platform default."""
    code = (country_code or "").strip().upper()
    defaults = COUNTRY_DEFAULTS.get(code)
    if defaults and defaults.get("locale"):
        return defaults["locale"]
    from app.services.shared.iso_geo_catalog import default_locale_for_country

    resolved = default_locale_for_country(code)
    if resolved:
        return resolved
    return DEFAULT_LOCALE


def merge_institution_settings(
    current: dict[str, Any] | None,
    *,
    country: str | None = None,
    timezone: str | None = None,
    locale: str | None = None,
    custom_bundle_field_key: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Apply institution profile updates to settings_json.

    ``currency`` is validated when provided but never written into settings_json;
    callers persist it on ``tenants.currency``.
    """
    if currency is not None and str(currency).strip():
        validate_currency_code(currency)

    out: dict[str, Any] = dict(current or {})

    if country is not None:
        code = country.strip().upper()
        out["country"] = code
        # Country change always resets derived timezone/locale unless caller overrides.
        if timezone is None:
            out["timezone"] = country_timezone_suggestion(code)
        if locale is None:
            out["locale"] = country_locale_suggestion(code)

    if timezone is not None:
        out["timezone"] = _validate_timezone(timezone.strip())
    if locale is not None:
        out["locale"] = locale.strip()
    if custom_bundle_field_key is not None:
        token = custom_bundle_field_key.strip()
        if token:
            out["custom_bundle_field_key"] = token
        else:
            out.pop("custom_bundle_field_key", None)

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
