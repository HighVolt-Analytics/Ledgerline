import pytest

from app.utils.abn_validator import is_valid_abn, normalize_abn


def test_valid_abns(valid_abns: list[str]) -> None:
    for abn in valid_abns:
        assert is_valid_abn(abn)


def test_invalid_abns(invalid_abns: list[str]) -> None:
    for abn in invalid_abns:
        assert not is_valid_abn(abn)


def test_normalize() -> None:
    assert normalize_abn("51 824 753 556") == "51824753556"


def test_spaces_valid() -> None:
    assert is_valid_abn("51 824 753 556")
