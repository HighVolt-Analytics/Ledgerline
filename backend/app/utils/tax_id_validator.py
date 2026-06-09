"""Tax ID validation: Australian ABN or equivalent international identifiers."""

import re

from app.utils.abn_validator import is_valid_abn, normalize_abn

_TAX_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-./\s]{5,24}$", re.I)


def is_acceptable_tax_id(value: str | None) -> bool:
    """
    True for a valid Australian ABN or a non-AU tax identifier (VAT, EIN, etc.).

    Brief: "ABN / Tax ID — Australian Business Number or equivalent".
    Eleven-digit values must pass the ABN checksum; other formats need 6–20
    alphanumeric characters after normalisation.
    """
    if not value or not str(value).strip():
        return False
    raw = str(value).strip()
    digits = normalize_abn(raw)
    if len(digits) == 11 and digits.isdigit():
        return is_valid_abn(digits)
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if 6 <= len(cleaned) <= 20 and _TAX_ID_PATTERN.match(raw):
        return True
    return False
