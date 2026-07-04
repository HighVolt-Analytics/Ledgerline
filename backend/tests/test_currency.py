from decimal import Decimal

from app.services.shared.currency import convert_to_base, sum_amounts_by_currency


def test_convert_to_base_usd() -> None:
    assert convert_to_base(Decimal("100"), "USD") == Decimal("155.00")


def test_sum_amounts_by_currency_mixed() -> None:
    total, by_currency = sum_amounts_by_currency(
        [
            ("AUD", Decimal("100")),
            ("USD", Decimal("100")),
        ]
    )
    assert by_currency["AUD"] == Decimal("100")
    assert by_currency["USD"] == Decimal("100")
    assert total == Decimal("255.00")
