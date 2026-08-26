"""Mask bank account identifiers in API payloads (ISO 27001 A.8.11 / data minimisation).

Full numbers stay in the database for matching and payment execution.
HTTP responses default to last-4 (account) / last-3 (BSB) / IBAN truncation.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.schemas.rule_book_config import BankDetails

MASK_CHAR = "•"
_MASK_CHARS = frozenset({"•", "*"})
_DIGIT_RUN_RE = re.compile(r"\d[\d \-]{4,}\d")

ACCOUNT_KEEP_LAST = 4
BSB_KEEP_LAST = 3
IBAN_KEEP_LAST = 4

_ACCOUNT_KEYS = frozenset(
    {
        "account_number",
        "accountNumber",
        "bank_account",
        "bank_account_number",
    }
)
_BSB_KEYS = frozenset({"bsb", "bank_bsb"})
_IBAN_KEYS = frozenset({"iban", "bank_iban"})
_COMPOSITE_KEYS = frozenset({"bank_details"})


def _alnum(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", value or "")


def looks_masked(value: str | None) -> bool:
    """True when a client is echoing a previously masked display value."""
    token = (value or "").strip()
    if not token:
        return False
    if any(ch in token for ch in _MASK_CHARS):
        return True
    return token.startswith("****")


def mask_secret(value: str | None, *, keep_last: int) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if looks_masked(raw):
        return raw
    compact = _alnum(raw)
    if len(compact) <= keep_last:
        return raw
    return f"{MASK_CHAR * 4}{compact[-keep_last:]}"


def mask_account(value: str | None) -> str:
    return mask_secret(value, keep_last=ACCOUNT_KEEP_LAST)


def mask_bsb(value: str | None) -> str:
    return mask_secret(value, keep_last=BSB_KEEP_LAST)


def mask_iban(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if looks_masked(raw):
        return raw
    compact = _alnum(raw)
    if len(compact) <= IBAN_KEEP_LAST + 2:
        return mask_account(raw)
    prefix = compact[:2]
    return f"{prefix}{MASK_CHAR * 2}{MASK_CHAR * 4}{compact[-IBAN_KEEP_LAST:]}"


def _mask_digit_run(match: re.Match[str]) -> str:
    token = match.group(0)
    digits = re.sub(r"\D", "", token)
    if len(digits) <= ACCOUNT_KEEP_LAST:
        return token
    if 5 <= len(digits) <= 7:
        return mask_bsb(token)
    return mask_account(token)


def mask_bank_details_text(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return _DIGIT_RUN_RE.sub(_mask_digit_run, raw)


def mask_bank_dict(bank: Mapping[str, Any] | None, *, reveal: bool = False) -> dict[str, Any]:
    payload = dict(bank or {})
    if reveal:
        payload.pop("masked", None)
        return payload
    if payload.get("account_number"):
        payload["account_number"] = mask_account(str(payload["account_number"]))
    if payload.get("bsb"):
        payload["bsb"] = mask_bsb(str(payload["bsb"]))
    if payload.get("iban"):
        payload["iban"] = mask_iban(str(payload["iban"]))
    payload.pop("masked", None)
    return payload


def mask_bank_details(bank: BankDetails, *, reveal: bool = False) -> BankDetails:
    return BankDetails.model_validate(mask_bank_dict(bank.model_dump(), reveal=reveal))


def merge_bank_update(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep stored secrets when the client posts a masked echo."""
    merged = dict(existing or {})
    for key, value in dict(incoming or {}).items():
        if key in {"masked", "bank_masked"}:
            continue
        if isinstance(value, str) and looks_masked(value):
            continue
        merged[key] = value
    return merged


def mask_extracted_bank_fields(
    fields: Mapping[str, Any] | None,
    *,
    reveal: bool = False,
) -> dict[str, Any] | None:
    if fields is None:
        return None
    out = dict(fields)
    if reveal:
        return out
    for key, value in list(out.items()):
        if not isinstance(value, str) or not value:
            continue
        lowered = key.lower()
        if lowered in _ACCOUNT_KEYS:
            out[key] = mask_account(value)
        elif lowered in _BSB_KEYS:
            out[key] = mask_bsb(value)
        elif lowered in _IBAN_KEYS:
            out[key] = mask_iban(value)
        elif lowered in _COMPOSITE_KEYS:
            out[key] = mask_bank_details_text(value)
    return out


def redact_bank_in_payload(value: Any) -> Any:
    """Recursively mask bank secrets in audit dumps and nested JSON."""
    if isinstance(value, dict):
        if "account_number" in value or "iban" in value or "bsb" in value:
            bank_like = any(k in value for k in ("account_number", "account_name", "bank_name"))
            if bank_like:
                nested = mask_bank_dict(value, reveal=False)
                return {k: redact_bank_in_payload(v) if k not in nested else nested[k] for k, v in value.items()}
        out: dict[str, Any] = {}
        for key, nested in value.items():
            lowered = key.lower()
            if lowered in _ACCOUNT_KEYS and isinstance(nested, str):
                out[key] = mask_account(nested)
            elif lowered in _BSB_KEYS and isinstance(nested, str):
                out[key] = mask_bsb(nested)
            elif lowered in _IBAN_KEYS and isinstance(nested, str):
                out[key] = mask_iban(nested)
            elif lowered in _COMPOSITE_KEYS and isinstance(nested, str):
                out[key] = mask_bank_details_text(nested)
            elif key == "bank" and isinstance(nested, dict):
                out[key] = mask_bank_dict(nested, reveal=False)
            else:
                out[key] = redact_bank_in_payload(nested)
        return out
    if isinstance(value, list):
        return [redact_bank_in_payload(item) for item in value]
    return value


def apply_bank_mask_to_master(data: Mapping[str, Any], *, reveal: bool) -> dict[str, Any]:
    out = dict(data)
    out["bank"] = mask_bank_dict(out.get("bank") or {}, reveal=reveal)
    out["bank_masked"] = not reveal
    return out


def _is_bank_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _ACCOUNT_KEYS or lowered in _BSB_KEYS or lowered in _IBAN_KEYS or lowered in _COMPOSITE_KEYS


def drop_masked_bank_values(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    """Omit client-echoed masked secrets so PATCH cannot overwrite stored numbers."""
    out: dict[str, Any] = {}
    for key, value in dict(fields or {}).items():
        if isinstance(value, str) and _is_bank_secret_key(key) and looks_masked(value):
            continue
        out[key] = value
    return out
