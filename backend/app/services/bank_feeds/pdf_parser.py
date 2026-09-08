"""Bank-statement PDF parser — multi-strategy extraction (tables, heuristics, text, OCR)."""

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
    DATE_TOKEN_RE,
    DIRECTION_UNCERTAIN_IMPORT_MSG,
    DIRECTION_UNCERTAIN_ROW_MSG,
    MONEY_TOKEN_RE,
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
    "date": (
        "date",
        "txn date",
        "transaction date",
        "value date",
        "posting date",
        "tran date",
        "trans date",
        "booking date",
        "process date",
        "processed date",
    ),
    "description": (
        "description",
        "narration",
        "particulars",
        "details",
        "memo",
        "transaction details",
        "transaction description",
        "remarks",
        "narrative",
        "payee",
        "merchant",
        "transaction",
    ),
    "debit": (
        "debit",
        "withdrawal",
        "withdrawals",
        "dr",
        "money out",
        "paid out",
        "outflow",
        "outflows",
        "payments",
        "payment",
        "debit amount",
        "withdrawals (dr)",
        "amount debited",
        "spent",
        "charge",
        "charges",
    ),
    "credit": (
        "credit",
        "deposit",
        "deposits",
        "cr",
        "money in",
        "paid in",
        "inflow",
        "inflows",
        "receipts",
        "receipt",
        "credit amount",
        "deposits (cr)",
        "amount credited",
        "received",
    ),
    "amount": (
        "amount",
        "amt",
        "transaction amount",
        "txn amount",
        "tran amount",
        "value",
        "sum",
    ),
    "direction": (
        "direction",
        "type",
        "dr/cr",
        "dr cr",
        "debit/credit",
        "cd",
        "c/d",
        "txn type",
        "transaction type",
        "flow",
    ),
    "balance": (
        "balance",
        "closing balance",
        "running balance",
        "available balance",
        "ledger balance",
        "book balance",
        "bal",
        "balance (aud)",
        "balance (usd)",
        "balance (inr)",
    ),
    "reference": (
        "reference",
        "ref",
        "ref no",
        "ref.",
        "cheque",
        "chq",
        "chq/ref",
        "cheque no",
        "transaction id",
        "txn id",
        "tran id",
        "fitid",
    ),
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

    @property
    def has_explicit_flow(self) -> bool:
        return bool(
            (self.debit is not None and self.credit is not None)
            or (self.amount is not None and self.direction is not None)
            or (self.amount is not None and self.balance is not None)
            or self.amount is not None
        )


def _normalize_header(value: str) -> str:
    text = (value or "").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"[_\.]+", " ", text)
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_column(header: str) -> str | None:
    """Match header labels by exact alias or whole-word alias — not loose substring."""
    norm = _normalize_header(header)
    if not norm:
        return None
    # Prefer longer aliases first to avoid "date" stealing "value date" already handled by exact.
    for key, aliases in _HEADER_ALIASES.items():
        if norm in aliases:
            return key
    for key, aliases in _HEADER_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", norm):
                return key
    return None


def _row_looks_like_header(row: list[str | None]) -> bool:
    hits = sum(1 for cell in row if _match_column(cell or ""))
    return hits >= 2 or _match_column((row[0] if row else "") or "") == "date" or any(
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
        or ("amount" in mapping and "balance" in mapping)
        or ("amount" in mapping)
        or ("debit" in mapping)
        or ("credit" in mapping)
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


def _looks_like_money(cell: str) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    text = re.sub(r"[\r\n]+", " ", text)
    try:
        parse_money_token(text)
        return True
    except ValueError:
        return bool(MONEY_TOKEN_RE.match(text.replace(" ", "")))


def _looks_like_date(cell: str) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    try:
        parse_statement_date(text)
        return True
    except ValueError:
        return bool(DATE_TOKEN_RE.search(text))


def _infer_columns_from_data(table: list[list[str | None]]) -> _ColumnMap | None:
    """When headers are missing/unknown, classify columns by cell content patterns."""
    if len(table) < 2:
        return None
    width = max((len(r) for r in table), default=0)
    if width < 3:
        return None

    # Skip likely header rows; sample up to 12 data rows.
    start = 1 if _row_looks_like_header(table[0]) else 0
    sample = [r for r in table[start : start + 15] if any((c or "").strip() for c in r)]
    if len(sample) < 2:
        return None

    date_scores = [0] * width
    money_scores = [0] * width
    text_scores = [0] * width
    for row in sample:
        for i in range(width):
            cell = (row[i] if i < len(row) else "") or ""
            if not cell.strip():
                continue
            if _looks_like_date(cell):
                date_scores[i] += 2
            elif _looks_like_money(cell):
                money_scores[i] += 1
            else:
                text_scores[i] += 1

    date_idx = max(range(width), key=lambda i: date_scores[i])
    if date_scores[date_idx] < 2:
        return None

    money_idxs = [i for i in range(width) if i != date_idx and money_scores[i] > 0]
    money_idxs.sort(key=lambda i: money_scores[i], reverse=True)
    if not money_idxs:
        return None

    text_idxs = [i for i in range(width) if i != date_idx and i not in money_idxs]
    text_idxs.sort(key=lambda i: text_scores[i], reverse=True)
    description = text_idxs[0] if text_idxs else None

    if len(money_idxs) >= 3:
        # Typical: debit, credit, balance (order by column index left→right).
        ordered = sorted(money_idxs[:3])
        return _ColumnMap(
            date=date_idx,
            description=description,
            debit=ordered[0],
            credit=ordered[1],
            balance=ordered[2],
        )
    if len(money_idxs) == 2:
        # amount + balance (direction from balance deltas)
        ordered = sorted(money_idxs)
        return _ColumnMap(
            date=date_idx,
            description=description,
            amount=ordered[0],
            balance=ordered[1],
        )
    # Single money column — treat as signed/absolute amount; direction via balance if possible.
    return _ColumnMap(
        date=date_idx,
        description=description,
        amount=money_idxs[0],
    )


def _resolve_columns(table: list[list[str | None]]) -> tuple[_ColumnMap | None, int | None, str]:
    """Return (columns, header_index, strategy)."""
    if not table:
        return None, None, "empty"
    for index, row in enumerate(table[:10]):
        candidate = _map_table_headers(row)
        if candidate is not None:
            return candidate, index, "headers"
    inferred = _infer_columns_from_data(table)
    if inferred is not None:
        start = 1 if _row_looks_like_header(table[0]) else 0
        return inferred, start - 1 if start else -1, "heuristic"
    return None, None, "none"


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
    description = re.sub(r"\s+", " ", description.replace("\n", " ")).strip()

    debit_raw = _cell(cells, columns.debit)
    credit_raw = _cell(cells, columns.credit)
    direction = ""
    amount = Decimal("0.00")

    if columns.debit is not None or columns.credit is not None:
        if debit_raw and credit_raw:
            # Some banks put 0.00 in the empty side.
            try:
                d_amt, _ = parse_money_token(debit_raw)
            except ValueError:
                d_amt = Decimal("0")
            try:
                c_amt, _ = parse_money_token(credit_raw)
            except ValueError:
                c_amt = Decimal("0")
            if d_amt > 0 and c_amt > 0:
                raise ValueError("Row has both debit and credit amounts")
            if d_amt > 0:
                amount, direction = d_amt, BankTxnDirection.DEBIT.value
            elif c_amt > 0:
                amount, direction = c_amt, BankTxnDirection.CREDIT.value
            elif debit_raw and not credit_raw:
                amount, _ = parse_money_token(debit_raw)
                direction = BankTxnDirection.DEBIT.value
            elif credit_raw:
                amount, _ = parse_money_token(credit_raw)
                direction = BankTxnDirection.CREDIT.value
            else:
                raise ValueError("Amount is required")
        elif debit_raw:
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
                direction = ""  # may be filled by balance deltas
        else:
            raise ValueError("Amount is required")
    elif columns.amount is not None:
        amount_raw = _cell(cells, columns.amount)
        direction_raw = _cell(cells, columns.direction)
        amount, signed_dir = parse_money_token(amount_raw)
        if direction_raw:
            direction = parse_direction(direction_raw)
        elif signed_dir:
            direction = signed_dir
        else:
            direction = ""
    else:
        raise ValueError(DIRECTION_UNCERTAIN_ROW_MSG)

    balance_raw = _cell(cells, columns.balance)
    balance = parse_optional_balance(balance_raw) if balance_raw else None
    reference = _cell(cells, columns.reference) or None
    if reference:
        reference = re.sub(r"\s+", " ", reference.replace("\n", " ")).strip() or None
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
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError], int, str]:
    """Parse table cells into rows without balance/direction finalization."""
    if not table:
        return [], [], 0, "empty"

    columns, header_index, strategy = _resolve_columns(table)
    if columns is None:
        return [], [], 0, strategy

    data_start = (header_index + 1) if header_index is not None and header_index >= 0 else 0
    if header_index == -1:
        data_start = 0

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    row_number = 0
    for raw_row in table[data_start:]:
        if not any((cell or "").strip() for cell in raw_row):
            continue
        # Skip repeated header rows mid-table
        if _map_table_headers(raw_row) is not None:
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
    return rows, errors, row_number, strategy


def _parse_table_rows(table: list[list[str | None]]) -> CsvParseResult:
    rows, errors, candidate_count, strategy = _parse_table_rows_raw(table)
    if not rows:
        return CsvParseResult(
            rows=[],
            errors=errors,
            candidate_line_count=candidate_count,
            parse_meta={"extraction_method": "table", "column_strategy": strategy},
        )
    # Debit/credit or amount columns: keep continuity as warning only.
    soft = True
    accepted, all_errors = finalize_parsed_rows(
        rows, prior_errors=errors, reject_on_balance_continuity=not soft
    )
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate_count,
        parse_meta={"extraction_method": "table", "column_strategy": strategy},
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
            # Try default strategy, then lines-based for stubborn layouts.
            page_tables = page.extract_tables() or []
            if not page_tables:
                try:
                    page_tables = (
                        page.extract_tables(
                            table_settings={
                                "vertical_strategy": "text",
                                "horizontal_strategy": "text",
                            }
                        )
                        or []
                    )
                except Exception:
                    page_tables = []
            for table in page_tables:
                if table:
                    tables.append(table)
    return tables, "\n".join(text_parts)


def extract_pdf_plain_text(content: bytes) -> str:
    """Readable text from a bank-statement PDF (for account/currency/name hints)."""
    if not content or not content.startswith(b"%PDF"):
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    try:
        _tables, text = _extract_pdf_tables_and_text(tmp_path)
        return (text or "").strip()
    except Exception as exc:
        logger.debug("pdf_plain_text_failed", error=str(exc)[:200])
        return ""
    finally:
        tmp_path.unlink(missing_ok=True)


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
    strategies: list[str] = []
    for table in tables:
        rows, errors, candidate_count, strategy = _parse_table_rows_raw(table)
        strategies.append(strategy)
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
        row_offset += max(len(rows), candidate_count)
        candidate += candidate_count
        merged_errors.extend(errors)

    accepted, all_errors = finalize_parsed_rows(
        merged_rows,
        prior_errors=merged_errors,
        reject_on_balance_continuity=False,
    )
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate,
        parse_meta={
            "extraction_method": "table",
            "column_strategies": ",".join(strategies),
        },
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

    table_parsed = _merge_table_results(tables) if tables else CsvParseResult(rows=[], errors=[])
    if table_parsed.rows:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        return table_parsed

    # Prefer text fallback over hard-failing on unrecognized headers.
    text_parsed = parse_statement_text_block(text) if text.strip() else CsvParseResult(
        rows=[], errors=[]
    )
    if text_parsed.rows:
        text_parsed.parse_meta["extraction_method"] = extraction_method
        text_parsed.parse_meta["fallback"] = "text_after_table"
        return text_parsed

    # Table detected but every data row failed — return table errors when we had candidates.
    if tables and table_parsed.candidate_line_count > 0:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        table_parsed.parse_meta["failure"] = "table_rows_unparsed"
        return table_parsed

    if text_parsed.errors:
        text_parsed.parse_meta["extraction_method"] = extraction_method
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
            errors=[CsvParseError(0, DIRECTION_UNCERTAIN_IMPORT_MSG)],
            candidate_line_count=_count_date_like_lines(text),
            parse_meta={
                "extraction_method": extraction_method,
                "failure": "dated_lines_unparsed",
            },
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


# Back-compat for tests that monkeypatch / call private helpers.
def _table_has_unrecognized_flow_headers(table: list[list[str | None]]) -> bool:
    columns, _, strategy = _resolve_columns(table)
    return columns is None or strategy == "none"
