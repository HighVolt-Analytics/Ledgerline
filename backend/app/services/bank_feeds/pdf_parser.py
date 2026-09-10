"""Bank-statement PDF parser — multi-strategy extraction (tables, heuristics, text, OCR)."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.models.bank_feed import BankTxnDirection
from app.services.bank_feeds.parse_common import (
    CsvParseError,
    CsvParseResult,
    CapturedBalanceMarker,
    DATE_TOKEN_RE,
    DIRECTION_CONFIDENCE_HIGH,
    DIRECTION_UNCERTAIN_IMPORT_MSG,
    DIRECTION_UNCERTAIN_ROW_MSG,
    DateOrder,
    DocumentDateOrder,
    EXTRACTION_CONFIDENCE_MEDIUM,
    EXTRACTION_SOURCE_CONTINUATION_MERGE,
    EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE,
    MONEY_TOKEN_RE,
    MoneyFormat,
    ParsedBankCsvRow,
    DATE_PREFIX_RE,
    assign_stated_opening_closing,
    apply_stated_balance_continuity,
    collect_date_strings_from_text,
    finalize_parsed_rows,
    infer_document_date_order,
    is_balance_marker_description,
    is_boilerplate_statement_line,
    parse_direction,
    parse_money_token,
    parse_optional_balance,
    parse_statement_date,
    parse_statement_text_block,
    parse_statement_text_line,
    positive_money_present,
    stated_balances_to_parse_meta,
)
from app.services.bank_feeds.statement_parse_profile import (
    GENERIC_V1,
    StatementParseProfile,
    generic_header_aliases,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Run text fallback merge when date-like lines exceed table rows by this ratio.
TABLE_TEXT_COVERAGE_GAP_RATIO = 0.20

# Header-text matching — generic_v1 contents (kept for back-compat imports/tests).
_HEADER_ALIASES: dict[str, tuple[str, ...]] = generic_header_aliases()


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


def _match_column(
    header: str,
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> str | None:
    """Match header labels by exact alias or whole-word alias — not loose substring."""
    norm = _normalize_header(header)
    if not norm:
        return None
    alias_map = aliases or _HEADER_ALIASES
    # Prefer longer aliases first to avoid "date" stealing "value date" already handled by exact.
    for key, key_aliases in alias_map.items():
        if norm in key_aliases:
            return key
    for key, key_aliases in alias_map.items():
        for alias in sorted(key_aliases, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", norm):
                return key
    return None


def _row_looks_like_header(
    row: list[str | None],
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> bool:
    hits = sum(1 for cell in row if _match_column(cell or "", aliases=aliases))
    return hits >= 2 or _match_column((row[0] if row else "") or "", aliases=aliases) == "date" or any(
        _match_column(cell or "", aliases=aliases) == "date" for cell in row
    )


def _map_table_headers(
    header_row: list[str | None],
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> _ColumnMap | None:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        key = _match_column(cell or "", aliases=aliases)
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


def _looks_like_money(cell: str, *, money_format: MoneyFormat | None = None) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    text = re.sub(r"[\r\n]+", " ", text)
    try:
        parse_money_token(text, money_format=money_format)
        return True
    except ValueError:
        if money_format is None:
            return bool(MONEY_TOKEN_RE.match(text.replace(" ", "")))
        return False


def _looks_like_date(cell: str, *, date_order: DateOrder | None = None) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    try:
        parse_statement_date(text, date_order=date_order)
        return True
    except ValueError:
        return bool(DATE_TOKEN_RE.search(text))


def _infer_columns_from_data(
    table: list[list[str | None]],
    *,
    money_format: MoneyFormat | None = None,
    date_order: DateOrder | None = None,
    money_column_order_hint: tuple[str, ...] | None = None,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> _ColumnMap | None:
    """When headers are missing/unknown, classify columns by cell content patterns."""
    if len(table) < 2:
        return None
    width = max((len(r) for r in table), default=0)
    if width < 3:
        return None

    # Skip likely header rows; sample up to 12 data rows.
    start = 1 if _row_looks_like_header(table[0], aliases=aliases) else 0
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
            if _looks_like_date(cell, date_order=date_order):
                date_scores[i] += 2
            elif _looks_like_money(cell, money_format=money_format):
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
        ordered = sorted(money_idxs[:3])
        hint = money_column_order_hint
        if hint and len(hint) >= 3:
            role_map = {
                hint[0]: ordered[0],
                hint[1]: ordered[1],
                hint[2]: ordered[2],
            }
            return _ColumnMap(
                date=date_idx,
                description=description,
                debit=role_map.get("debit"),
                credit=role_map.get("credit"),
                amount=role_map.get("amount"),
                balance=role_map.get("balance"),
            )
        # Typical: debit, credit, balance (order by column index left→right).
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


def _resolve_columns(
    table: list[list[str | None]],
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
    money_format: MoneyFormat | None = None,
    date_order: DateOrder | None = None,
    money_column_order_hint: tuple[str, ...] | None = None,
) -> tuple[_ColumnMap | None, int | None, str]:
    """Return (columns, header_index, strategy)."""
    if not table:
        return None, None, "empty"
    for index, row in enumerate(table[:10]):
        candidate = _map_table_headers(row, aliases=aliases)
        if candidate is not None:
            return candidate, index, "headers"
    inferred = _infer_columns_from_data(
        table,
        money_format=money_format,
        date_order=date_order,
        money_column_order_hint=money_column_order_hint,
        aliases=aliases,
    )
    if inferred is not None:
        start = 1 if _row_looks_like_header(table[0], aliases=aliases) else 0
        return inferred, start - 1 if start else -1, "heuristic"
    return None, None, "none"


def _cell(row: list[str | None], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _row_looks_incomplete_for_stitch(row: ParsedBankCsvRow) -> bool:
    """Closing-signal heuristic for cross-page description stitching."""
    if row.balance is None:
        return True
    desc = (row.description or "").rstrip()
    if not desc:
        return True
    if desc.endswith(("-", ",", "/", "&", "(")):
        return True
    return False


def _continuation_text_from_raw_row(
    raw_row: list[str | None],
    columns: _ColumnMap | None,
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
    money_format: MoneyFormat | None = None,
    date_order: DateOrder | None = None,
) -> str | None:
    """Return text to append when the row has no date/amount — else None."""
    if not any((cell or "").strip() for cell in raw_row):
        return None
    if _map_table_headers(raw_row, aliases=aliases) is not None:
        return None
    cells = [(cell or "").strip() for cell in raw_row if (cell or "").strip()]
    joined = re.sub(r"\s+", " ", " ".join(cells)).strip()
    if not joined or is_boilerplate_statement_line(joined):
        return None
    for cell in cells:
        if _looks_like_date(cell, date_order=date_order) or _looks_like_money(
            cell, money_format=money_format
        ):
            return None
    if columns is not None:
        date_raw = _cell(raw_row, columns.date)
        if date_raw and _looks_like_date(date_raw, date_order=date_order):
            return None
        for idx in (columns.debit, columns.credit, columns.amount, columns.balance):
            money_raw = _cell(raw_row, idx)
            if money_raw and _looks_like_money(money_raw, money_format=money_format):
                return None
    return joined


def _append_continuation_description(
    row: ParsedBankCsvRow, extra: str
) -> ParsedBankCsvRow:
    from dataclasses import replace

    return replace(
        row,
        description=f"{row.description} {extra}".strip(),
        extraction_source=EXTRACTION_SOURCE_CONTINUATION_MERGE,
        extraction_confidence=EXTRACTION_CONFIDENCE_MEDIUM,
    )


def _txn_fingerprint(row: ParsedBankCsvRow) -> str:
    """Full import fingerprint (includes direction). Not used for table/text merge identity."""
    from app.services.bank_feeds.fingerprint import compute_fingerprint, normalize_description

    return compute_fingerprint(
        txn_date=row.txn_date,
        amount=row.amount,
        direction=row.direction,
        description_normalized=normalize_description(row.description),
    )


def _merge_identity_key(row: ParsedBankCsvRow) -> str:
    """Table/text merge identity: date|amount|description — direction ignored."""
    from app.services.bank_feeds.fingerprint import normalize_description

    amt = f"{row.amount.quantize(Decimal('0.01')):.2f}"
    return "|".join(
        [
            row.txn_date.isoformat(),
            amt,
            normalize_description(row.description),
        ]
    )


_DIRECTION_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _direction_confidence_rank(confidence: str | None) -> int:
    return _DIRECTION_CONF_RANK.get(confidence or "", 0)


def _resolve_table_text_direction_conflict(
    table_row: ParsedBankCsvRow,
    text_row: ParsedBankCsvRow,
) -> ParsedBankCsvRow:
    """One row only: higher direction_confidence wins; ties keep table + low extraction flag."""
    from dataclasses import replace

    from app.services.bank_feeds.parse_common import (
        DIRECTION_DISAGREEMENT_NOTE,
        EXTRACTION_CONFIDENCE_LOW,
    )

    if table_row.direction == text_row.direction:
        return table_row

    table_rank = _direction_confidence_rank(table_row.direction_confidence)
    text_rank = _direction_confidence_rank(text_row.direction_confidence)

    if text_rank > table_rank:
        return replace(
            table_row,
            direction=text_row.direction,
            direction_confidence=text_row.direction_confidence,
        )
    if table_rank > text_rank:
        return table_row

    # Same confidence, conflicting direction — table wins, surface for review.
    return replace(
        table_row,
        extraction_confidence=EXTRACTION_CONFIDENCE_LOW,
        extraction_note=DIRECTION_DISAGREEMENT_NOTE,
    )


def _merge_table_and_text_results(
    table_parsed: CsvParseResult,
    text_parsed: CsvParseResult,
) -> CsvParseResult:
    """Merge text rows into table rows.

    Identity for this step only: date|amount|normalized_description (direction
    ignored). Full import fingerprints elsewhere are unchanged. On direction
    disagreement, prefer higher direction_confidence; ties keep the table
    direction and flag extraction_confidence=low.
    """
    from dataclasses import replace

    ordered: list[ParsedBankCsvRow] = []
    by_identity: dict[str, int] = {}  # identity key -> index in ordered

    for row in table_parsed.rows:
        key = _merge_identity_key(row)
        by_identity[key] = len(ordered)
        ordered.append(row)

    added = 0
    for row in text_parsed.rows:
        key = _merge_identity_key(row)
        if key in by_identity:
            idx = by_identity[key]
            ordered[idx] = _resolve_table_text_direction_conflict(ordered[idx], row)
            continue
        tagged = replace(
            row,
            extraction_source=EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE,
            extraction_confidence=EXTRACTION_CONFIDENCE_MEDIUM,
        )
        by_identity[key] = len(ordered)
        ordered.append(tagged)
        added += 1

    renumbered = [replace(row, row_number=i) for i, row in enumerate(ordered, start=1)]

    meta = dict(table_parsed.parse_meta or {})
    meta["text_fallback_merge"] = "true"
    meta["text_fallback_merge_added"] = str(added)
    if added:
        meta["source"] = EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE
    errors = list(table_parsed.errors) + [
        err for err in text_parsed.errors if err not in table_parsed.errors
    ]
    return CsvParseResult(
        rows=renumbered,
        errors=errors,
        extracted_count=len(renumbered),
        candidate_line_count=max(
            table_parsed.candidate_line_count, text_parsed.candidate_line_count
        ),
        skipped_line_count=table_parsed.skipped_line_count + text_parsed.skipped_line_count,
        parse_meta=meta,
    )


def _row_from_table_cells(
    cells: list[str | None],
    columns: _ColumnMap,
    *,
    row_number: int,
    date_order: DateOrder | None = None,
    money_format: MoneyFormat | None = None,
) -> ParsedBankCsvRow:
    txn_date = parse_statement_date(_cell(cells, columns.date), date_order=date_order)
    description = _cell(cells, columns.description)
    if not description:
        description = _cell(cells, columns.reference) or "Bank transaction"
    description = re.sub(r"\s+", " ", description.replace("\n", " ")).strip()

    debit_raw = _cell(cells, columns.debit)
    credit_raw = _cell(cells, columns.credit)
    direction = ""
    amount = Decimal("0.00")
    explicit_direction = False

    if columns.debit is not None or columns.credit is not None:
        if debit_raw and credit_raw:
            # Some banks put 0.00 in the empty side.
            try:
                d_amt, _ = parse_money_token(debit_raw, money_format=money_format)
            except ValueError:
                d_amt = Decimal("0")
            try:
                c_amt, _ = parse_money_token(credit_raw, money_format=money_format)
            except ValueError:
                c_amt = Decimal("0")
            if d_amt > 0 and c_amt > 0:
                raise ValueError("Row has both debit and credit amounts")
            if d_amt > 0:
                amount, direction = d_amt, BankTxnDirection.DEBIT.value
                explicit_direction = True
            elif c_amt > 0:
                amount, direction = c_amt, BankTxnDirection.CREDIT.value
                explicit_direction = True
            elif debit_raw and not credit_raw:
                amount, _ = parse_money_token(debit_raw, money_format=money_format)
                direction = BankTxnDirection.DEBIT.value
                explicit_direction = True
            elif credit_raw:
                amount, _ = parse_money_token(credit_raw, money_format=money_format)
                direction = BankTxnDirection.CREDIT.value
                explicit_direction = True
            else:
                raise ValueError("Amount is required")
        elif debit_raw:
            amount, _ = parse_money_token(debit_raw, money_format=money_format)
            direction = BankTxnDirection.DEBIT.value
            explicit_direction = True
        elif credit_raw:
            amount, _ = parse_money_token(credit_raw, money_format=money_format)
            direction = BankTxnDirection.CREDIT.value
            explicit_direction = True
        elif columns.amount is not None:
            amount_raw = _cell(cells, columns.amount)
            direction_raw = _cell(cells, columns.direction)
            amount, signed_dir = parse_money_token(amount_raw, money_format=money_format)
            if direction_raw:
                direction = parse_direction(direction_raw)
                explicit_direction = True
            elif signed_dir:
                direction = signed_dir
                explicit_direction = True
            else:
                direction = ""  # may be filled by balance deltas
        else:
            raise ValueError("Amount is required")
    elif columns.amount is not None:
        amount_raw = _cell(cells, columns.amount)
        direction_raw = _cell(cells, columns.direction)
        amount, signed_dir = parse_money_token(amount_raw, money_format=money_format)
        if direction_raw:
            direction = parse_direction(direction_raw)
            explicit_direction = True
        elif signed_dir:
            direction = signed_dir
            explicit_direction = True
        else:
            direction = ""
    else:
        raise ValueError(DIRECTION_UNCERTAIN_ROW_MSG)

    balance_raw = _cell(cells, columns.balance)
    balance = parse_optional_balance(balance_raw, money_format=money_format) if balance_raw else None
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
        direction_confidence=DIRECTION_CONFIDENCE_HIGH if explicit_direction else None,
    )


def _row_description_for_marker(cells: list[str | None], columns: _ColumnMap) -> str:
    description = _cell(cells, columns.description)
    if not description:
        description = _cell(cells, columns.reference) or ""
    return re.sub(r"\s+", " ", description.replace("\n", " ")).strip()


def _table_row_has_flow_amount(
    cells: list[str | None],
    columns: _ColumnMap,
    *,
    money_format: MoneyFormat | None,
) -> bool:
    if positive_money_present(_cell(cells, columns.debit), money_format=money_format):
        return True
    if positive_money_present(_cell(cells, columns.credit), money_format=money_format):
        return True
    if positive_money_present(_cell(cells, columns.amount), money_format=money_format):
        return True
    return False


def _try_capture_balance_marker_row(
    cells: list[str | None],
    columns: _ColumnMap,
    *,
    encounter_index: int,
    date_order: DateOrder | None,
    money_format: MoneyFormat | None,
    phrases: tuple[str, ...],
) -> CapturedBalanceMarker | None:
    """Return a marker when description matches and no debit/credit/amount is present."""
    description = _row_description_for_marker(cells, columns)
    if not is_balance_marker_description(description, phrases):
        return None
    if _table_row_has_flow_amount(cells, columns, money_format=money_format):
        return None
    txn_date: date | None
    try:
        txn_date = parse_statement_date(_cell(cells, columns.date), date_order=date_order)
    except ValueError:
        txn_date = None
    balance_raw = _cell(cells, columns.balance)
    balance = (
        parse_optional_balance(balance_raw, money_format=money_format)
        if balance_raw
        else None
    )
    return CapturedBalanceMarker(
        encounter_index=encounter_index,
        txn_date=txn_date,
        balance=balance,
        description=description,
    )


def _finalize_with_stated_balances(
    rows: list[ParsedBankCsvRow],
    errors: list[CsvParseError],
    markers: list[CapturedBalanceMarker],
    *,
    reject_on_balance_continuity: bool,
    refine_direction_mode: str,
    base_meta: dict[str, str],
    skipped_line_count: int = 0,
    candidate_line_count: int = 0,
) -> CsvParseResult:
    accepted, all_errors = finalize_parsed_rows(
        rows,
        prior_errors=errors,
        reject_on_balance_continuity=reject_on_balance_continuity,
        refine_direction_mode=refine_direction_mode,  # type: ignore[arg-type]
    )
    stated_opening, stated_closing = assign_stated_opening_closing(markers, accepted)
    accepted, stated_errors = apply_stated_balance_continuity(
        accepted,
        stated_opening=stated_opening,
        stated_closing=stated_closing,
    )
    all_errors = list(all_errors) + stated_errors
    meta = dict(base_meta)
    meta.update(stated_balances_to_parse_meta(stated_opening, stated_closing))
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate_line_count,
        skipped_line_count=skipped_line_count,
        parse_meta=meta,
    )


def _join_split_table_cells(cells: list[str | None]) -> str:
    """Join pdfplumber-split cells, repairing mid-word / mid-amount column cuts.

    Phantom tables often bisect tokens (``GREENL``|``EAF``, ``6,500``|``.00``).
    Alphanumeric abutments and digit/``.`` abutments are concatenated without a space.
    """
    parts = [(c or "").strip() for c in cells if (c or "").strip()]
    if not parts:
        return ""
    out = parts[0]
    for part in parts[1:]:
        if not out:
            out = part
            continue
        left, right = out[-1], part[0]
        # Mid-word letter split (GREENL|EAF) or shattered decimals (6,500|.00).
        # Do NOT join digit↔letter (date|description) or digit↔digit (amount|balance).
        if left.isalpha() and right.isalpha():
            out += part
        elif left.isdigit() and right == ".":
            out += part
        elif left in ",." and right.isdigit():
            out += part
        else:
            out = f"{out} {part}"
    return re.sub(r"\s+", " ", out).strip()


def _is_table_txn_date_candidate(
    date_raw: str, *, date_order: DateOrder | None = None
) -> bool:
    """True when the date cell looks like a real transaction date prefix.

    Used as the table-path analogue of ``DATE_PREFIX_RE`` gating in text fallback:
    header/footer cells (``SUMMIT NA``, ``Statement``, ``Page 1 of 1``) must not
    enter ``parse_statement_date`` / amount parsing as transaction candidates.
    """
    text = (date_raw or "").strip()
    if not text:
        return False
    if DATE_PREFIX_RE.match(text):
        return True
    # Whole-cell date only — reject prose that merely contains a date token.
    if len(text) > 40:
        return False
    try:
        parse_statement_date(text, date_order=date_order)
    except ValueError:
        return False
    return bool(DATE_TOKEN_RE.fullmatch(text) or DATE_PREFIX_RE.match(text))


def _try_recover_row_from_joined_cells(
    raw_row: list[str | None],
    *,
    row_number: int,
    date_order: DateOrder | None,
    money_format: MoneyFormat | None,
) -> ParsedBankCsvRow | None:
    """Re-parse a shattered table row as one text line after mid-word column splits."""
    joined = _join_split_table_cells(raw_row)
    if not joined or not DATE_PREFIX_RE.match(joined):
        return None
    try:
        parsed = parse_statement_text_line(
            joined,
            row_number=row_number,
            date_order=date_order,
            money_format=money_format,
        )
    except ValueError:
        return None
    return parsed


def _parse_table_rows_raw(
    table: list[list[str | None]],
    *,
    date_order: DateOrder | None = None,
    previous_rows: list[ParsedBankCsvRow] | None = None,
    require_incomplete_for_cross_table_stitch: bool = True,
    aliases: dict[str, tuple[str, ...]] | None = None,
    money_format: MoneyFormat | None = None,
    money_column_order_hint: tuple[str, ...] | None = None,
    balance_marker_phrases: tuple[str, ...] | None = None,
    markers_out: list[CapturedBalanceMarker] | None = None,
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError], int, str]:
    """Parse table cells into rows without balance/direction finalization.

    Continuation rows (no date/amount, text only) append onto the prior row in
    this table, or onto ``previous_rows[-1]`` when stitching across page tables.
    """
    if not table:
        return [], [], 0, "empty"

    columns, header_index, strategy = _resolve_columns(
        table,
        aliases=aliases,
        money_format=money_format,
        date_order=date_order,
        money_column_order_hint=money_column_order_hint,
    )
    if columns is None:
        return [], [], 0, strategy

    data_start = (header_index + 1) if header_index is not None and header_index >= 0 else 0
    if header_index == -1:
        data_start = 0

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    row_number = 0
    encounter_index = 0
    phrases = balance_marker_phrases or ()
    prior_bucket = previous_rows if previous_rows is not None else []
    cont_kw = dict(aliases=aliases, money_format=money_format, date_order=date_order)

    for raw_row in table[data_start:]:
        if not any((cell or "").strip() for cell in raw_row):
            continue
        # Skip repeated header rows mid-table
        if _map_table_headers(raw_row, aliases=aliases) is not None:
            continue

        marker = _try_capture_balance_marker_row(
            raw_row,
            columns,
            encounter_index=encounter_index,
            date_order=date_order,
            money_format=money_format,
            phrases=phrases,
        )
        if marker is not None:
            if markers_out is not None:
                markers_out.append(marker)
            encounter_index += 1
            continue

        cont_text = _continuation_text_from_raw_row(raw_row, columns, **cont_kw)
        if cont_text is not None:
            if rows:
                rows[-1] = _append_continuation_description(rows[-1], cont_text)
                continue
            if prior_bucket:
                anchor = prior_bucket[-1]
                if (not require_incomplete_for_cross_table_stitch) or _row_looks_incomplete_for_stitch(
                    anchor
                ):
                    prior_bucket[-1] = _append_continuation_description(anchor, cont_text)
                    continue

        # Line candidacy (table-path): require a real date in the date column.
        # Phantom/heuristic tables otherwise feed headers like "SUMMIT NA" into
        # parse_statement_date and emit Unrecognized-date errors for every noise row.
        date_raw = _cell(raw_row, columns.date)
        if not _is_table_txn_date_candidate(date_raw, date_order=date_order):
            # Empty/non-date rows with no prior txn: silent skip (not a candidate).
            continue

        row_number += 1
        encounter_index += 1
        try:
            rows.append(
                _row_from_table_cells(
                    raw_row,
                    columns,
                    row_number=row_number,
                    date_order=date_order,
                    money_format=money_format,
                )
            )
        except ValueError as exc:
            # Mid-word column split: rejoin cells and parse as a text transaction line.
            recovered = _try_recover_row_from_joined_cells(
                raw_row,
                row_number=row_number,
                date_order=date_order,
                money_format=money_format,
            )
            if recovered is not None:
                rows.append(recovered)
                continue
            # Date/amount parse failed — retry as continuation before recording error.
            fallback_text = _continuation_text_from_raw_row(raw_row, columns, **cont_kw)
            if fallback_text is None:
                # Still try joining non-empty cells when date cell was junk.
                joined = _join_split_table_cells(raw_row)
                if (
                    joined
                    and not is_boilerplate_statement_line(joined)
                    and not any(
                        _looks_like_money(c, money_format=money_format)
                        for c in [(c or "").strip() for c in raw_row if (c or "").strip()]
                    )
                ):
                    fallback_text = joined
            if fallback_text and rows:
                rows[-1] = _append_continuation_description(rows[-1], fallback_text)
                row_number -= 1
                encounter_index -= 1
                continue
            if fallback_text and prior_bucket and _row_looks_incomplete_for_stitch(prior_bucket[-1]):
                prior_bucket[-1] = _append_continuation_description(
                    prior_bucket[-1], fallback_text
                )
                row_number -= 1
                encounter_index -= 1
                continue
            errors.append(
                CsvParseError(
                    row_number=row_number,
                    message=str(exc),
                    raw={str(i): (cell or "") for i, cell in enumerate(raw_row)},
                )
            )
    return rows, errors, row_number, strategy


def _parse_table_rows(
    table: list[list[str | None]],
    *,
    date_order: DateOrder | None = None,
    profile: StatementParseProfile | None = None,
) -> CsvParseResult:
    profile = profile or GENERIC_V1
    money_format = MoneyFormat.from_profile(profile)
    aliases = dict(profile.header_aliases)
    markers: list[CapturedBalanceMarker] = []
    rows, errors, candidate_count, strategy = _parse_table_rows_raw(
        table,
        date_order=date_order,
        aliases=aliases,
        money_format=money_format,
        money_column_order_hint=profile.money_column_order_hint,
        balance_marker_phrases=tuple(profile.balance_marker_phrases),
        markers_out=markers,
    )
    if not rows and not markers:
        return CsvParseResult(
            rows=[],
            errors=errors,
            candidate_line_count=candidate_count,
            parse_meta={"extraction_method": "table", "column_strategy": strategy},
        )
    return _finalize_with_stated_balances(
        rows,
        errors,
        markers,
        reject_on_balance_continuity=False,
        refine_direction_mode=profile.refine_direction_mode,
        base_meta={
            "extraction_method": "table",
            "column_strategy": strategy,
            "parse_profile_id": profile.profile_id,
        },
        skipped_line_count=len(markers),
        candidate_line_count=candidate_count,
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


def _extract_text_with_ocr_fallback(
    path: Path,
    local_text: str,
    *,
    ocr_min_chars: int = 120,
    ocr_trigger_mode: str = "chars_only",
    date_like_line_count: int = 0,
) -> tuple[str, str]:
    local_len = len((local_text or "").strip())
    needs_ocr = local_len < ocr_min_chars
    if ocr_trigger_mode == "chars_or_low_date_density":
        needs_ocr = needs_ocr or date_like_line_count < 2
    if not needs_ocr:
        return local_text, "pdfplumber"

    try:
        from app.services.extraction.pdf_page_text_service import extract_pdf_page_texts

        extraction = extract_pdf_page_texts(path)
        upgraded = "\n".join(page.text for page in extraction.pages if page.text)
        if len(upgraded.strip()) > local_len:
            logger.info(
                "bank_feed_pdf_ocr_upgrade",
                path=str(path),
                local_chars=local_len,
                upgraded_chars=len(upgraded.strip()),
            )
            return upgraded, "ocr"
    except Exception as exc:
        logger.warning("bank_feed_pdf_ocr_failed", path=str(path), error=str(exc))

    return local_text, "pdfplumber"


def _collect_date_strings_from_tables(tables: list[list[list[str | None]]]) -> list[str]:
    found: list[str] = []
    for table in tables:
        for row in table:
            for cell in row:
                text = (cell or "").strip()
                if not text:
                    continue
                for token in DATE_TOKEN_RE.findall(text):
                    found.append(token if isinstance(token, str) else token[0])
    return found


def _merge_table_results(
    tables: list[list[list[str | None]]],
    *,
    date_order: DateOrder | None = None,
    profile: StatementParseProfile | None = None,
) -> CsvParseResult:
    profile = profile or GENERIC_V1
    money_format = MoneyFormat.from_profile(profile)
    aliases = dict(profile.header_aliases)
    merged_rows: list[ParsedBankCsvRow] = []
    merged_errors: list[CsvParseError] = []
    markers: list[CapturedBalanceMarker] = []
    row_offset = 0
    candidate = 0
    strategies: list[str] = []
    for table in tables:
        # Pass merged_rows so page-break continuations can stitch onto prior page.
        rows, errors, candidate_count, strategy = _parse_table_rows_raw(
            table,
            date_order=date_order,
            previous_rows=merged_rows,
            require_incomplete_for_cross_table_stitch=True,
            aliases=aliases,
            money_format=money_format,
            money_column_order_hint=profile.money_column_order_hint,
            balance_marker_phrases=tuple(profile.balance_marker_phrases),
            markers_out=markers,
        )
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
                    direction_confidence=row.direction_confidence,
                    extraction_source=row.extraction_source,
                    extraction_confidence=row.extraction_confidence,
                    extraction_note=row.extraction_note,
                )
            )
        row_offset += max(len(rows), candidate_count)
        candidate += candidate_count
        merged_errors.extend(errors)

    return _finalize_with_stated_balances(
        merged_rows,
        merged_errors,
        markers,
        reject_on_balance_continuity=False,
        refine_direction_mode=profile.refine_direction_mode,
        base_meta={
            "extraction_method": "table",
            "column_strategies": ",".join(strategies),
            "parse_profile_id": profile.profile_id,
        },
        skipped_line_count=len(markers),
        candidate_line_count=candidate,
    )


def _count_date_like_lines(
    text: str,
    *,
    balance_marker_phrases: tuple[str, ...] | None = None,
) -> int:
    """Count lines that look like transaction date rows for coverage-gap checks.

    Excludes boilerplate and balance-marker rows (OPENING/CLOSING BALANCE, B/F, …)
    so clean header tables are not falsely treated as under-extracted when those
    dated marker lines inflate the text-side count.
    """
    count = 0
    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if not cleaned or is_boilerplate_statement_line(cleaned):
            continue
        date_match = DATE_PREFIX_RE.match(cleaned)
        if not date_match:
            continue
        rest = cleaned[date_match.end() :].strip()
        desc_for_marker = re.sub(
            r"(\s+\(?\s*(?:Rs\.?\s*)?(?:\$|€|£|₹)?[\d,]+\.\d{2}\)?)+$",
            "",
            rest,
            flags=re.IGNORECASE,
        ).strip()
        if is_balance_marker_description(desc_for_marker, balance_marker_phrases):
            continue
        count += 1
    return count


def parse_bank_statement_pdf(
    content: bytes,
    *,
    preferred_date_order: DateOrder | None = None,
    profile: StatementParseProfile | None = None,
) -> CsvParseResult:
    """Parse a bank statement PDF into canonical transaction rows."""
    profile = profile or GENERIC_V1
    money_format = MoneyFormat.from_profile(profile)
    coverage_gap = profile.table_text_coverage_gap_ratio

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
        preliminary_date_like = _count_date_like_lines(
            local_text, balance_marker_phrases=tuple(profile.balance_marker_phrases)
        )
        text, extraction_method = _extract_text_with_ocr_fallback(
            tmp_path,
            local_text,
            ocr_min_chars=profile.ocr_min_chars,
            ocr_trigger_mode=profile.ocr_trigger_mode,
            date_like_line_count=preliminary_date_like,
        )
    except Exception as exc:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, f"Could not read PDF: {exc}")],
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    date_samples = _collect_date_strings_from_tables(tables) + collect_date_strings_from_text(
        text
    )
    if profile.date_order in {"dmy", "mdy", "ymd"}:
        doc_dates = DocumentDateOrder(order=profile.date_order, assumed=False)  # type: ignore[arg-type]
    else:
        # date_order == "auto" — Phase 0 document-level inference unchanged.
        doc_dates = infer_document_date_order(
            date_samples,
            preferred_order=preferred_date_order,
        )
    date_meta = {
        "date_order": doc_dates.order,
        "date_order_assumed": "true" if doc_dates.assumed else "false",
        "parse_profile_id": profile.profile_id,
    }

    table_parsed = (
        _merge_table_results(tables, date_order=doc_dates.order, profile=profile)
        if tables
        else CsvParseResult(rows=[], errors=[])
    )
    if table_parsed.rows:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        table_parsed.parse_meta.update(date_meta)
        date_like = _count_date_like_lines(
            text, balance_marker_phrases=tuple(profile.balance_marker_phrases)
        )
        table_count = len(table_parsed.rows)
        # Phase 1.1 — if text has materially more *transaction* date-like lines,
        # merge text fallback. Marker/boilerplate lines are excluded from date_like.
        if text.strip() and date_like > table_count * (1.0 + coverage_gap):
            text_parsed = parse_statement_text_block(
                text,
                preferred_date_order=preferred_date_order,
                date_order=doc_dates,
                money_format=money_format,
                refine_direction_mode=profile.refine_direction_mode,
            )
            if text_parsed.rows:
                merged = _merge_table_and_text_results(table_parsed, text_parsed)
                merged.parse_meta["extraction_method"] = extraction_method
                merged.parse_meta.update(date_meta)
                merged.parse_meta["date_like_line_count"] = str(date_like)
                merged.parse_meta["table_row_count_before_merge"] = str(table_count)
                return merged
        return table_parsed

    # Prefer text fallback over hard-failing on unrecognized headers.
    text_parsed = (
        parse_statement_text_block(
            text,
            preferred_date_order=preferred_date_order,
            date_order=doc_dates,
            money_format=money_format,
            refine_direction_mode=profile.refine_direction_mode,
        )
        if text.strip()
        else CsvParseResult(rows=[], errors=[])
    )
    if text_parsed.rows:
        text_parsed.parse_meta["extraction_method"] = extraction_method
        text_parsed.parse_meta["fallback"] = "text_after_table"
        text_parsed.parse_meta.update(date_meta)
        return text_parsed

    # Table detected but every data row failed — return table errors when we had candidates.
    if tables and table_parsed.candidate_line_count > 0:
        table_parsed.parse_meta["extraction_method"] = extraction_method
        table_parsed.parse_meta["failure"] = "table_rows_unparsed"
        table_parsed.parse_meta.update(date_meta)
        return table_parsed

    if text_parsed.errors:
        text_parsed.parse_meta["extraction_method"] = extraction_method
        text_parsed.parse_meta.update(date_meta)
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
            parse_meta={"extraction_method": extraction_method, **date_meta},
        )

    if _count_date_like_lines(text) > 0:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, DIRECTION_UNCERTAIN_IMPORT_MSG)],
            candidate_line_count=_count_date_like_lines(text),
            parse_meta={
                "extraction_method": extraction_method,
                "failure": "dated_lines_unparsed",
                **date_meta,
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
        parse_meta={"extraction_method": extraction_method, **date_meta},
    )


# Back-compat for tests that monkeypatch / call private helpers.
def _table_has_unrecognized_flow_headers(table: list[list[str | None]]) -> bool:
    columns, _, strategy = _resolve_columns(table)
    return columns is None or strategy == "none"
