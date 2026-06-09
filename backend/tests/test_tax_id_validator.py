from app.utils.abn_validator import is_valid_abn
from app.utils.tax_id_validator import is_acceptable_tax_id


def test_valid_abn_accepted() -> None:
    assert is_acceptable_tax_id("51824753556")
    assert is_valid_abn("51824753556")


def test_foreign_vat_accepted() -> None:
    assert is_acceptable_tax_id("IE6388047V")


def test_invalid_eleven_digit_rejected() -> None:
    assert not is_acceptable_tax_id("12345678901")
