from app.utils.abn_validator import is_abn_format, is_valid_abn


def test_is_abn_format_eleven_digits() -> None:
    assert is_abn_format("63 110 305 305")
    assert is_abn_format("63110305305")


def test_is_abn_format_rejects_short() -> None:
    assert not is_abn_format("12345")


def test_checksum_stricter_than_format() -> None:
    assert is_abn_format("63110305305")
    assert not is_valid_abn("63110305305")
