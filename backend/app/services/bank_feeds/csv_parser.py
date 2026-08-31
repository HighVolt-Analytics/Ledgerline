"""Canonical bank-statement CSV parser (Phase 2 — one fixed template)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.bank_feed import BankTxnDirection

CANONICAL_HEADERS = (
    "Date",
    "Description",
    "Amount",
    "Direction",
    "Balance",
    "Reference",
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%Y",
)


@dataclass(frozen=True)
class ParsedBankCsvRow:
    row_number: int  # 1-based data row (header is row 0 conceptually)
    txn_date: date
    description: str
    amount: Decimal
    direction: str  # debit | credit
    balance: Decimal | None
    # Free-text statement reference (invoice no., etc.) — NOT a unique txn id.
    reference: str | None


@dataclass(frozen=True)
class CsvParseError:
    row_number: int
    message: str
    raw: dict[str, str] | None = None


@dataclass(frozen=True)
class CsvParseResult:
    rows: list[ParsedBankCsvRow]
    errors: list[CsvParseError]


def _parse_date(raw: str) -> date:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Date is required")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {text!r}")


def _parse_amount(raw: str) -> Decimal:
    text = (raw or "").strip().replace(",", "")
    if not text:
        raise ValueError("Amount is required")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw!r}") from exc
    if value < 0:
        raise ValueError("Amount must be non-negative; use Direction for money in/out")
    return value.quantize(Decimal("0.01"))


def _parse_direction(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in {"in", "credit", "cr", "money_in", "deposit"}:
        return BankTxnDirection.CREDIT.value
    if text in {"out", "debit", "dr", "money_out", "withdrawal", "payment"}:
        return BankTxnDirection.DEBIT.value
    raise ValueError(
        f"Direction must be in/out (or credit/debit); got {raw!r}"
    )


def _parse_optional_balance(raw: str) -> Decimal | None:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid balance: {raw!r}") from exc


def parse_canonical_bank_csv(content: bytes) -> CsvParseResult:
    """Parse the fixed Phase-2 template. Encoding: UTF-8 (with BOM tolerated)."""
    if not content or not content.strip():
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "Uploaded file is empty")])

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, "File must be UTF-8 encoded CSV")],
        )

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "CSV has no header row")])

    normalized_headers = [(h or "").strip() for h in reader.fieldnames]
    missing = [h for h in CANONICAL_HEADERS if h not in normalized_headers]
    if missing:
        return CsvParseResult(
            rows=[],
            errors=[
                CsvParseError(
                    0,
                    "Missing required columns: "
                    + ", ".join(missing)
                    + f". Expected: {', '.join(CANONICAL_HEADERS)}",
                )
            ],
        )

    # Remap rows to canonical header keys (tolerate trailing spaces on headers).
    header_map = {(h or "").strip(): h for h in reader.fieldnames}

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    for index, raw_row in enumerate(reader, start=1):
        try:
            get = lambda key: (raw_row.get(header_map[key]) or "").strip()  # noqa: E731
            txn_date = _parse_date(get("Date"))
            description = get("Description")
            if not description:
                raise ValueError("Description is required")
            amount = _parse_amount(get("Amount"))
            direction = _parse_direction(get("Direction"))
            balance = _parse_optional_balance(get("Balance"))
            reference = get("Reference") or None
            rows.append(
                ParsedBankCsvRow(
                    row_number=index,
                    txn_date=txn_date,
                    description=description,
                    amount=amount,
                    direction=direction,
                    balance=balance,
                    reference=reference,
                )
            )
        except ValueError as exc:
            errors.append(
                CsvParseError(
                    row_number=index,
                    message=str(exc),
                    raw={k: (v or "") for k, v in raw_row.items()},
                )
            )

    return CsvParseResult(rows=rows, errors=errors)
