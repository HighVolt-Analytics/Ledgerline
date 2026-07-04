"""Convert invoice amounts to a single reporting currency for dashboard aggregates."""

from collections import defaultdict
from decimal import Decimal

# Static rates to AUD — update via config when multi-currency billing is added.
_FX_TO_AUD: dict[str, Decimal] = {
    "AUD": Decimal("1"),
    "USD": Decimal("1.55"),
    "INR": Decimal("0.018"),
    "GBP": Decimal("1.95"),
    "EUR": Decimal("1.65"),
    "NZD": Decimal("0.92"),
}

BASE_CURRENCY = "AUD"


def fx_rate_to_base(currency: str | None) -> Decimal:
    code = (currency or BASE_CURRENCY).upper()
    return _FX_TO_AUD.get(code, Decimal("1"))


def convert_to_base(amount: Decimal | None, currency: str | None) -> Decimal:
    if amount is None:
        return Decimal("0")
    return amount * fx_rate_to_base(currency)


def sum_amounts_by_currency(
    rows: list[tuple[str | None, Decimal | None]],
) -> tuple[Decimal, dict[str, Decimal]]:
    """Return (total in AUD, raw totals grouped by currency code)."""
    by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    total_base = Decimal("0")
    for currency, amount in rows:
        if amount is None:
            continue
        code = (currency or BASE_CURRENCY).upper()
        by_currency[code] += amount
        total_base += convert_to_base(amount, code)
    return total_base, dict(by_currency)
