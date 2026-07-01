"""Australian Business Number checksum validation."""

import re

_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def normalize_abn(value: str) -> str:
    return re.sub(r"\D", "", value)


def storage_abn(value: str | None) -> str | None:
    """Digits-only ABN for invoice.abn (VARCHAR(11)); None if not exactly 11 digits."""
    if value is None or not str(value).strip():
        return None
    digits = normalize_abn(str(value))
    if len(digits) != 11:
        return None
    return digits


def is_abn_format(abn: str) -> bool:
    """Test-phase check: exactly 11 digits after normalisation."""
    digits_str = normalize_abn(abn)
    return len(digits_str) == 11 and digits_str.isdigit()


def is_valid_abn(abn: str) -> bool:
    """Full Australian Business Number checksum (production)."""
    digits_str = normalize_abn(abn)
    if len(digits_str) != 11 or not digits_str.isdigit():
        return False
    digits = [int(c) for c in digits_str]
    digits[0] -= 1
    return sum(w * d for w, d in zip(_WEIGHTS, digits, strict=True)) % 89 == 0
