"""Convert invoice amounts to a single reporting currency for dashboard aggregates."""

from collections import defaultdict
from decimal import Decimal

from app.tenant_settings import COUNTRY_CURRENCY, DEFAULT_COUNTRY

# Static rates relative to AUD — used as an FX graph; convert via cross rates.
_FX_TO_AUD: dict[str, Decimal] = {
    "AUD": Decimal("1"),
    "USD": Decimal("1.55"),
    "INR": Decimal("0.018"),
    "GBP": Decimal("1.95"),
    "EUR": Decimal("1.65"),
    "NZD": Decimal("0.92"),
    "SGD": Decimal("1.15"),
    "AED": Decimal("0.42"),
}

# Platform reporting fallback when no tenant context is available.
BASE_CURRENCY = COUNTRY_CURRENCY[DEFAULT_COUNTRY]


def fx_rate_to_base(currency: str | None, *, base: str | None = None) -> Decimal:
    """Rate to convert ``currency`` into ``base`` (default platform base)."""
    target = (base or BASE_CURRENCY).upper()
    code = (currency or target).upper()
    if code == target:
        return Decimal("1")
    to_aud = _FX_TO_AUD.get(code, Decimal("1"))
    base_to_aud = _FX_TO_AUD.get(target, Decimal("1"))
    if base_to_aud == 0:
        return Decimal("1")
    return to_aud / base_to_aud


def convert_to_base(
    amount: Decimal | None,
    currency: str | None,
    *,
    base: str | None = None,
) -> Decimal:
    if amount is None:
        return Decimal("0")
    return amount * fx_rate_to_base(currency, base=base)


def sum_amounts_by_currency(
    rows: list[tuple[str | None, Decimal | None]],
    *,
    base: str | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    """Return (total in base currency, raw totals grouped by currency code)."""
    target = (base or BASE_CURRENCY).upper()
    by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_base = Decimal("0")
    for currency, amount in rows:
        if amount is None:
            continue
        code = (currency or target).upper()
        by_currency[code] += amount
        total_base += convert_to_base(amount, code, base=target)
    return total_base, dict(by_currency)
