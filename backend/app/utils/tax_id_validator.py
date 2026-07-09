"""Tax ID validation — strategy dispatched by jurisdiction tax_id_kind."""

from __future__ import annotations

import re

from app.utils.abn_validator import is_valid_abn, normalize_abn

_TAX_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-./\s]{5,24}$", re.I)
_GSTIN_PATTERN = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
    re.I,
)
_UEN_PATTERN = re.compile(r"^[0-9]{8,10}[A-Z]$|^[ST]\d{2}[A-Z]{2}\d{4}[A-Z]$", re.I)


def _generic_tax_id_ok(raw: str) -> bool:
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    return 6 <= len(cleaned) <= 20 and bool(_TAX_ID_PATTERN.match(raw))


def is_acceptable_tax_id(
    value: str | None,
    *,
    tax_id_kind: str | None = None,
) -> bool:
    """
    True for a tax identifier acceptable under ``tax_id_kind``.

    When kind is omitted, accepts a valid ABN (11-digit checksum) **or** a
    generic international identifier — legacy behaviour for callers without
    tenant context. Prefer passing the jurisdiction pack's ``tax_id_kind``.
    """
    if not value or not str(value).strip():
        return False
    raw = str(value).strip()
    kind = (tax_id_kind or "").strip().lower() or None

    if kind == "abn":
        return is_valid_abn(raw)

    if kind == "gstin":
        cleaned = re.sub(r"\s+", "", raw.upper())
        return bool(_GSTIN_PATTERN.match(cleaned))

    if kind == "uen":
        cleaned = re.sub(r"[\s\-]", "", raw.upper())
        return bool(_UEN_PATTERN.match(cleaned)) or _generic_tax_id_ok(raw)

    if kind in {"vat", "ein", "ird", "generic"}:
        # Do not treat accidental 11-digit non-ABN values as failures for
        # non-AU kinds; require checksum only when kind is explicitly abn.
        digits = normalize_abn(raw)
        if kind != "abn" and len(digits) == 11 and digits.isdigit():
            # Ambiguous — accept if checksum passes OR generic format OK.
            return is_valid_abn(digits) or _generic_tax_id_ok(raw)
        return _generic_tax_id_ok(raw)

    # Legacy unspecified: 11-digit must be valid ABN; else generic.
    digits = normalize_abn(raw)
    if len(digits) == 11 and digits.isdigit():
        return is_valid_abn(digits)
    return _generic_tax_id_ok(raw)


def storage_tax_id(
    value: str | None,
    *,
    tax_id_kind: str | None = None,
) -> str | None:
    """
    Value suitable for ``invoice.abn`` (legacy VARCHAR(11) column).

    - AU ``abn`` kind: digits-only 11-char ABN.
    - Other kinds: return None for the narrow column (store full id in
      party / extracted_fields); callers should use tax_id fields.
    """
    if value is None or not str(value).strip():
        return None
    kind = (tax_id_kind or "").strip().lower()
    if kind in {"", "abn"}:
        from app.utils.abn_validator import storage_abn

        return storage_abn(value)
    return None
