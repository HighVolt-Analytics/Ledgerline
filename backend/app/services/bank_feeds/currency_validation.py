"""Bank account currency validation — ISO 4217 via shared catalog (pycountry)."""

from __future__ import annotations

from app.tenant_settings import UnsupportedCurrencyError, validate_currency_code


class UnsupportedBankCurrencyError(UnsupportedCurrencyError):
    """Raised when currency is not a valid ISO 4217 code."""


def validate_bank_account_currency(code: str | None) -> str:
    try:
        return validate_currency_code(code)
    except UnsupportedCurrencyError as exc:
        raise UnsupportedBankCurrencyError(str(exc)) from exc
