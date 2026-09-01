"""Bank account currency allowlist — matches frontend CURRENCIES / CURRENCY_SEEDS."""

from __future__ import annotations

from app.currency_catalog import ACTIVE_CURRENCY_CODES


class UnsupportedBankCurrencyError(ValueError):
    """Raised when currency is not in the platform-supported bank-feed allowlist."""


def validate_bank_account_currency(code: str | None) -> str:
    token = (code or "").strip().upper()
    if len(token) != 3:
        raise UnsupportedBankCurrencyError("currency must be a 3-letter ISO code")
    if token not in ACTIVE_CURRENCY_CODES:
        supported = ", ".join(sorted(ACTIVE_CURRENCY_CODES))
        raise UnsupportedBankCurrencyError(
            f"Unsupported currency {token!r}; supported: {supported}"
        )
    return token
