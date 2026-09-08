"""Canonical bank-statement CSV parser (Phase 2 — one fixed template)."""

from __future__ import annotations

import csv
import io

from app.services.bank_feeds.parse_common import (
    CsvParseError,
    CsvParseResult,
    ParsedBankCsvRow,
    parse_direction,
    parse_optional_balance,
    parse_statement_amount,
    parse_statement_date,
)

CANONICAL_HEADERS = (
    "Date",
    "Description",
    "Amount",
    "Direction",
    "Balance",
    "Reference",
)

# Re-export shared types for existing imports.
__all__ = [
    "CANONICAL_HEADERS",
    "CsvParseError",
    "CsvParseResult",
    "ParsedBankCsvRow",
    "parse_canonical_bank_csv",
]


def parse_canonical_bank_csv(content: bytes) -> CsvParseResult:
    """Parse the fixed Phase-2 template. Encoding: UTF-8 (with BOM tolerated).

    Leading metadata lines (e.g. ``Account Number: 123456789``) are skipped until
    the canonical header row is found so bank identity can live above the grid.
    """
    if not content or not content.strip():
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "Uploaded file is empty")])

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, "File must be UTF-8 encoded CSV")],
        )

    lines = text.splitlines()
    header_idx: int | None = None
    for i, line in enumerate(lines):
        cols = [(c or "").strip() for c in next(csv.reader([line]), [])]
        if all(h in cols for h in CANONICAL_HEADERS):
            header_idx = i
            break
    if header_idx is None:
        return CsvParseResult(
            rows=[],
            errors=[
                CsvParseError(
                    0,
                    "Missing required columns: "
                    + ", ".join(CANONICAL_HEADERS)
                    + f". Expected: {', '.join(CANONICAL_HEADERS)}",
                )
            ],
        )

    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))
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

    header_map = {(h or "").strip(): h for h in reader.fieldnames}

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    for index, raw_row in enumerate(reader, start=1):
        try:
            get = lambda key: (raw_row.get(header_map[key]) or "").strip()  # noqa: E731
            txn_date = parse_statement_date(get("Date"))
            description = get("Description")
            if not description:
                raise ValueError("Description is required")
            amount = parse_statement_amount(get("Amount"))
            direction = parse_direction(get("Direction"))
            balance = parse_optional_balance(get("Balance") or None)
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
