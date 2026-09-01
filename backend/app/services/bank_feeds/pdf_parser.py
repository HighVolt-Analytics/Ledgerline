"""Bank-statement PDF parser — multi-strategy extraction (tables, text, OCR)."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.models.bank_feed import BankTxnDirection
from app.services.bank_feeds.parse_common import (
    CsvParseError,
    CsvParseResult,
    DIRECTION_UNCERTAIN_IMPORT_MSG,
    DIRECTION_UNCERTAIN_ROW_MSG,
    ParsedBankCsvRow,
    DATE_PREFIX_RE,
    finalize_parsed_rows,
    parse_direction,
    parse_money_token,
    parse_optional_balance,
    parse_statement_date,
    parse_statement_text_block,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Header-text matching (not column position): normalized cell text vs aliases.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "txn date", "transaction date", "value date", "posting date"),
    "description": (
        "description",
        "narration",
        "particulars",
        "details",
        "memo",
        "transaction details",
    ),
    "debit": ("debit", "withdrawal", "withdrawals", "dr", "money out", "paid out"),
    "credit": ("credit", "deposit", "deposits", "cr", "money in", "paid in"),
    "amount": ("amount", "amt", "transaction amount"),
    "direction": ("direction", "type", "dr/cr", "dr cr"),
    "balance": ("balance", "closing balance", "running balance", "available balance"),
    "reference": ("reference", "ref", "ref no", "cheque", "chq", "chq/ref"),
}


@dataclass(frozen=True)
class _ColumnMap:
    date: int | None = None
    description: int | None = None
    debit: int | None = None
    credit: int | None = None
    amount: int | None = None
    direction: int | None = None
    balance: int | None = None
    reference: int | None = None


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _match_column(header: str) -> str | None:
    """Match header labels by exact alias or whole-word alias — not loose substring."""
    norm = _normalize_header(header)
    if not norm:
        return None
    for key, aliases in _HEADER_ALIASES.items():
        if norm in aliases:
            return key
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", norm):
                return key
    return None


def _row_looks_like_header(row: list[str | None]) -> bool:
    return _match_column((row[0] if row else "") or "") == "date" or any(
        _match_column(cell or "") == "date" for cell in row
    )


def _map_table_headers(header_row: list[str | None]) -> _ColumnMap | None:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        key = _match_column(cell or "")
        if key and key not in mapping:
            mapping[key] = index
    if "date" not in mapping:
        return None
    has_flow = (
        ("debit" in mapping and "credit" in mapping)
        or ("amount" in mapping and "direction" in mapping)
        or ("debit" in mapping and "credit" in mapping and "amount" not in mapping)
    )
    if not has_flow:
        return None
    return _ColumnMap(
        date=mapping.get("date"),
        description=mapping.get("description"),
        debit=mapping.get("debit"),
        credit=mapping.get("credit"),
        amount=mapping.get("amount"),
        direction=mapping.get("direction"),
        balance=mapping.get("balance"),
        reference=mapping.get("reference"),
    )


def _table_has_unrecognized_flow_headers(table: list[list[str | None]]) -> bool:
    """True when a header row has Date but no mappable Debit/Credit/Amount+Direction."""
    for row in table[:8]:
        if not _row_looks_like_header(row):
            continue
        if _map_table_headers(row) is None:
            return True
    return False


def _cell(row: list[str | None], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _row_from_table_cells(
    cells: list[str | None],
    columns: _ColumnMap,
    *,
    row_number: int,
) -> ParsedBankCsvRow:
    txn_date = parse_statement_date(_cell(cells, columns.date))
    description = _cell(cells, columns.description)
    if not description:
        description = _cell(cells, columns.reference) or "Bank transaction"

    debit_raw = _cell(cells, columns.debit)
    credit_raw = _cell(cells, columns.credit)
    direction = ""
    if debit_raw and credit_raw:
        raise ValueError("Row has both debit and credit amounts")
    if debit_raw:
        amount, _ = parse_money_token(debit_raw)
        direction = BankTxnDirection.DEBIT.value
    elif credit_raw:
        amount, _ = parse_money_token(credit_raw)
        direction = BankTxnDirection.CREDIT.value
    elif columns.amount is not None:
        amount_raw = _cell(cells, columns.amount)
        direction_raw = _cell(cells, columns.direction)
        amount, signed_dir = parse_money_token(amount_raw)
        if direction_raw:
            direction = parse_direction(direction_raw)
        elif signed_dir:
            direction = signed_dir
        else:
            raise ValueError(DIRECTION_UNCERTAIN_ROW_MSG)
    else:
        raise ValueError(DIRECTION_UNCERTAIN_ROW_MSG)

    balance_raw = _cell(cells, columns.balance)
    balance = parse_optional_balance(balance_raw) if balance_raw else None
    reference = _cell(cells, columns.reference) or None
    return ParsedBankCsvRow(
        row_number=row_number,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        balance=balance,
        reference=reference,
    )


def _parse_table_rows_raw(
    table: list[list[str | None]],
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError], int]:
    """Parse table cells into rows without balance/direction finalization."""
    if not table:
        return [], [], 0

    header_index = None
    columns: _ColumnMap | None = None
    for index, row in enumerate(table[:8]):
        candidate = _map_table_headers(row)
        if candidate is not None:
            header_index = index
            columns = candidate
            break
    if columns is None or header_index is None:
        return [], [], 0

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    row_number = 0
    for raw_row in table[header_index + 1 :]:
        if not any((cell or "").strip() for cell in raw_row):
            continue
        row_number += 1
        try:
            rows.append(_row_from_table_cells(raw_row, columns, row_number=row_number))
        except ValueError as exc:
            errors.append(
                CsvParseError(
                    row_number=row_number,
                    message=str(exc),
                    raw={str(i): (cell or "") for i, cell in enumerate(raw_row)},
                )
            )
    return rows, errors, row_number


def _parse_table_rows(table: list[list[str | None]]) -> CsvParseResult:
    rows, errors, candidate_count = _parse_table_rows_raw(table)
    if not rows:
        return CsvParseResult(
            rows=[],
            errors=errors,
            candidate_line_count=candidate_count,
            parse_meta={"extraction_method": "table"},
        )
    accepted, all_errors = finalize_parsed_rows(rows, prior_errors=errors)
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate_count,
        parse_meta={"extraction_method": "table"},
    )


def _extract_pdf_tables_and_text(path: Path) -> tuple[list[list[list[str | None]]], str]:
    tables: list[list[list[str | None]]] = []
    text_parts: list[str] = []
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text)
            for table in page.extract_tables() or []:
                if table:
                    tables.append(table)
    return tables, "\n".join(text_parts)


def _extract_text_with_ocr_fallback(path: Path, local_text: str) -> tuple[str, str]:
    if len((local_text or "").strip()) >= 120:
        return local_text, "pdfplumber"

    try:
        from app.services.extraction.pdf_page_text_service import extract_pdf_page_texts

        extraction = extract_pdf_page_texts(path)
        upgraded = "\n".join(page.text for page in extraction.pages if page.text)
        if len(upgraded.strip()) > len((local_text or "").strip()):
            logger.info(
                "bank_feed_pdf_ocr_upgrade",
                path=str(path),
                local_chars=len((local_text or "").strip()),
                upgraded_chars=len(upgraded.strip()),
            )
            return upgraded, "ocr"
    except Exception as exc:
        logger.warning("bank_feed_pdf_ocr_failed", path=str(path), error=str(exc))

    return local_text, "pdfplumber"


def _merge_table_results(tables: list[list[list[str | None]]]) -> CsvParseResult:
    merged_rows: list[ParsedBankCsvRow] = []
    merged_errors: list[CsvParseError] = []
    row_offset = 0
    candidate = 0
    meta: dict[str, str] = {"extraction_method": "table"}
    for table in tables:
        rows, errors, candidate_count = _parse_table_rows_raw(table)
        for row in rows:
            merged_rows.append(
                ParsedBankCsvRow(
                    row_number=row_offset + row.row_number,
                    txn_date=row.txn_date,
                    description=row.description,
                    amount=row.amount,
                    direction=row.direction,
                    balance=row.balance,
                    reference=row.reference,
                )
            )
        row_offset += len(rows)
        candidate += candidate_count
        merged_errors.extend(errors)

    accepted, all_errors = finalize_parsed_rows(merged_rows, prior_errors=merged_errors)
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate,
        parse_meta=meta,
    )


def _count_date_like_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if cleaned and DATE_PREFIX_RE.match(cleaned):
            count += 1
    return count


def parse_bank_statement_pdf(content: bytes) -> CsvParseResult:
    """Parse a bank statement PDF into canonical transaction rows."""
    if not content or not content.strip():
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "Uploaded file is empty")])
    if not content.startswith(b"%PDF"):
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, "File is not a valid PDF")],
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)

    try:
        tables, local_text = _extract_pdf_tables_and_text(tmp_path)
        text, extraction_method = _extract_text_with_ocr_fallback(tmp_path, local_text)
    except Exception as exc:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, f"Could not read PDF: {exc}")],
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    unrecognized_table = any(_table_has_unrecognized_flow_headers(t) for t in tables)
    if unrecognized_table and not any(
        _parse_table_rows_raw(t)[0]
        for t in tables
        if not _table_has_unrecognized_flow_headers(t)
    ):
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, DIRECTION_UNCERTAIN_IMPORT_MSG)],
            parse_meta={"extraction_method": extraction_method, "failure": "unrecognized_table_headers"},
        )

    table_parsed = _merge_table_results(tables)
    if table_parsed.rows:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        return table_parsed

    # Table detected but every data row failed — return table errors, not text-fallback noise.
    if tables and table_parsed.candidate_line_count > 0:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        table_parsed.parse_meta["failure"] = "table_rows_unparsed"
        return table_parsed

    if tables and unrecognized_table:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, DIRECTION_UNCERTAIN_IMPORT_MSG)],
            parse_meta={"extraction_method": extraction_method, "failure": "unrecognized_table_headers"},
        )

    text_parsed = parse_statement_text_block(text)
    text_parsed.parse_meta["extraction_method"] = extraction_method
    if text_parsed.rows or text_parsed.errors:
        return text_parsed

    if not text.strip():
        return CsvParseResult(
            rows=[],
            errors=[
                CsvParseError(
                    0,
                    "No readable text found in PDF. Export CSV from your bank, "
                    "or upload a text-based statement PDF.",
                )
            ],
            parse_meta={"extraction_method": extraction_method},
        )

    if _count_date_like_lines(text) > 0:
        return CsvParseResult(
            rows=[],
            errors=[
                CsvParseError(
                    0,
                    DIRECTION_UNCERTAIN_IMPORT_MSG,
                )
            ],
            candidate_line_count=_count_date_like_lines(text),
            parse_meta={"extraction_method": extraction_method, "failure": "dated_lines_unparsed"},
        )

    logger.warning(
        "bank_feed_pdf_parse_no_rows",
        extraction_method=extraction_method,
        text_preview=text[:400],
    )
    return CsvParseResult(
        rows=[],
        errors=[
            CsvParseError(
                0,
                "Could not parse transactions from PDF. Export CSV from your bank instead.",
            )
        ],
        parse_meta={"extraction_method": extraction_method},
    )
