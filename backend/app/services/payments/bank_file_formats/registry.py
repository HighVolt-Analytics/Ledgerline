"""Registry of available batch bank-payment file formats, keyed by code."""

from __future__ import annotations

from app.services.payments.bank_file_formats.aba import AbaFileFormat
from app.services.payments.bank_file_formats.base import BankFileFormat, BankFileFormatError

_REGISTRY: dict[str, BankFileFormat] = {}


def _register(fmt: BankFileFormat) -> None:
    _REGISTRY[fmt.code] = fmt


_register(AbaFileFormat())


def get_bank_file_format(code: str) -> BankFileFormat:
    key = (code or "").strip().upper()
    fmt = _REGISTRY.get(key)
    if fmt is None:
        raise BankFileFormatError(f"Unsupported bank file format: {code!r}")
    return fmt


def available_bank_file_formats() -> list[str]:
    return sorted(_REGISTRY.keys())
