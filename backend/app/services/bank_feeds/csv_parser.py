"""Bank-statement CSV parser — canonical template + profile alias/encoding fallback."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from app.models.bank_feed import BankTxnDirection
from app.services.bank_feeds.parse_common import (
    DIRECTION_CONFIDENCE_HIGH,
    CsvParseError,
    CsvParseResult,
    CapturedBalanceMarker,
    DateOrder,
    DocumentDateOrder,
    MoneyFormat,
    ParsedBankCsvRow,
    assign_stated_opening_closing,
    apply_stated_balance_continuity,
    finalize_parsed_rows,
    infer_document_date_order,
    is_balance_marker_description,
    parse_direction,
    parse_money_token,
    parse_optional_balance,
    parse_statement_amount,
    parse_statement_date,
    positive_money_present,
    stated_balances_to_parse_meta,
)
from app.services.bank_feeds.pdf_parser import _match_column
from app.services.bank_feeds.statement_parse_profile import (
    GENERIC_V1,
    StatementParseProfile,
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


def _decode_csv_text(
    content: bytes, *, encodings: tuple[str, ...]
) -> tuple[str, str]:
    """Decode with profile encoding_fallbacks.

    Prefers ``utf-8-sig`` when listed so BOM files match the pre-Phase-3 happy path
    (``content.decode("utf-8-sig")``) even if the profile lists ``utf-8`` first.
    """
    ordered: list[str] = []
    if any((e or "").strip().lower() == "utf-8-sig" for e in encodings):
        ordered.append("utf-8-sig")
    for encoding in encodings:
        name = (encoding or "").strip()
        if not name:
            continue
        if name not in ordered:
            ordered.append(name)

    tried: list[str] = []
    for name in ordered:
        tried.append(name)
        try:
            return content.decode(name), name
        except UnicodeDecodeError:
            continue
        except LookupError:
            continue
    tried_list = ", ".join(tried) if tried else "(none)"
    raise ValueError(f"Could not decode CSV. Tried encodings: {tried_list}")


def _is_exact_canonical_header(cols: list[str]) -> bool:
    return all(h in cols for h in CANONICAL_HEADERS)


def _resolve_logical_columns(
    fieldnames: list[str],
    *,
    aliases: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    """Map logical keys (date, amount, …) → raw CSV header names."""
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        key = _match_column(raw or "", aliases=aliases)
        if key and key not in mapping:
            mapping[key] = raw
    return mapping


def _has_required_flow(mapping: dict[str, str]) -> bool:
    return (
        ("amount" in mapping and "direction" in mapping)
        or ("amount" in mapping and "balance" in mapping)
        or ("amount" in mapping)
        or ("debit" in mapping and "credit" in mapping)
        or ("debit" in mapping)
        or ("credit" in mapping)
    )


def _missing_required_fields(mapping: dict[str, str]) -> list[str]:
    missing: list[str] = []
    if "date" not in mapping:
        missing.append("date")
    if "description" not in mapping:
        missing.append("description")
    if not _has_required_flow(mapping):
        missing.append("amount/direction (or debit/credit columns)")
    return missing


def _find_header_row(
    lines: list[str],
    *,
    aliases: dict[str, tuple[str, ...]],
) -> tuple[int, list[str], str, list[str]]:
    """Return (index, fieldnames, mode, missing) where mode is canonical|aliases|none.

    On failure, ``missing`` lists unresolved required logical fields from the
    best partial alias candidate (if any), so callers can fail loudly.
    """
    best_partial: tuple[int, list[str], list[str]] | None = None
    for i, line in enumerate(lines):
        cols = [(c or "").strip() for c in next(csv.reader([line]), [])]
        if not any(cols):
            continue
        if _is_exact_canonical_header(cols):
            return i, cols, "canonical", []
        mapping = _resolve_logical_columns(cols, aliases=aliases)
        missing = _missing_required_fields(mapping)
        if not missing:
            return i, cols, "aliases", []
        # Prefer the candidate that resolved the most logical keys.
        if best_partial is None or len(mapping) > len(
            _resolve_logical_columns(best_partial[1], aliases=aliases)
        ):
            best_partial = (i, cols, missing)
    if best_partial is not None:
        return best_partial[0], best_partial[1], "none", best_partial[2]
    return -1, [], "none", ["date", "description", "amount/direction (or debit/credit columns)"]


def _amount_and_direction_from_row(
    *,
    get_logical,
    money_format: MoneyFormat | None,
) -> tuple[Decimal, str]:
    """Reuse PDF-style debit/credit vs amount+direction resolution."""
    debit_raw = get_logical("debit")
    credit_raw = get_logical("credit")
    amount_raw = get_logical("amount")
    direction_raw = get_logical("direction")

    if debit_raw or credit_raw:
        if debit_raw and credit_raw:
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
                return d_amt, BankTxnDirection.DEBIT.value
            if c_amt > 0:
                return c_amt, BankTxnDirection.CREDIT.value
            if debit_raw and not credit_raw:
                amount, _ = parse_money_token(debit_raw, money_format=money_format)
                return amount, BankTxnDirection.DEBIT.value
            if credit_raw:
                amount, _ = parse_money_token(credit_raw, money_format=money_format)
                return amount, BankTxnDirection.CREDIT.value
            raise ValueError("Amount is required")
        if debit_raw:
            amount, _ = parse_money_token(debit_raw, money_format=money_format)
            return amount, BankTxnDirection.DEBIT.value
        amount, _ = parse_money_token(credit_raw, money_format=money_format)
        return amount, BankTxnDirection.CREDIT.value

    if not amount_raw:
        raise ValueError("Amount is required")
    amount, signed_dir = parse_money_token(amount_raw, money_format=money_format)
    if direction_raw:
        return amount, parse_direction(direction_raw)
    if signed_dir:
        return amount, signed_dir
    return amount, ""


def parse_canonical_bank_csv(
    content: bytes,
    *,
    preferred_date_order: DateOrder | None = None,
    profile: StatementParseProfile | None = None,
) -> CsvParseResult:
    """Parse bank CSV: exact canonical template (unchanged), else profile aliases.

    Money/date use shared parse_common helpers with the active StatementParseProfile.
    """
    profile = profile or GENERIC_V1
    money_format = MoneyFormat.from_profile(profile)
    aliases = {k: tuple(v) for k, v in profile.csv_header_aliases.items()}

    if not content or not content.strip():
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "Uploaded file is empty")])

    try:
        text, used_encoding = _decode_csv_text(
            content, encodings=profile.encoding_fallbacks
        )
    except ValueError as exc:
        return CsvParseResult(
            rows=[],
            errors=[CsvParseError(0, str(exc))],
        )

    lines = text.splitlines()
    header_idx, header_cols, header_mode, header_missing = _find_header_row(
        lines, aliases=aliases
    )
    if header_mode == "none":
        found_preview = header_cols or []
        if not found_preview:
            for line in lines[:5]:
                cols = [(c or "").strip() for c in next(csv.reader([line]), [])]
                if cols:
                    found_preview = cols
                    break
        found_msg = (
            f" Found headers: {', '.join(found_preview)}."
            if found_preview
            else " No header row detected."
        )
        return CsvParseResult(
            rows=[],
            errors=[
                CsvParseError(
                    0,
                    "Missing required fields after alias resolution: "
                    + ", ".join(header_missing)
                    + "."
                    + found_msg,
                )
            ],
        )
    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        return CsvParseResult(rows=[], errors=[CsvParseError(0, "CSV has no header row")])

    raw_fieldnames = [(h or "").strip() for h in reader.fieldnames]
    # Preserve DictReader's original keys (may differ only by whitespace).
    fieldname_by_strip = {(h or "").strip(): h for h in reader.fieldnames}

    if header_mode == "canonical":
        missing = [h for h in CANONICAL_HEADERS if h not in raw_fieldnames]
        if missing:
            return CsvParseResult(
                rows=[],
                errors=[
                    CsvParseError(
                        0,
                        "Missing required columns: "
                        + ", ".join(missing)
                        + f". Expected: {', '.join(CANONICAL_HEADERS)}. "
                        f"Found headers: {', '.join(raw_fieldnames)}",
                    )
                ],
            )
        logical_to_raw = {h: fieldname_by_strip[h] for h in CANONICAL_HEADERS}
        column_strategy = "canonical"
    else:
        # Alias path — map via csv_header_aliases (generic_v1 includes PDF vocabulary).
        logical_map = _resolve_logical_columns(raw_fieldnames, aliases=aliases)
        missing = _missing_required_fields(logical_map)
        if missing:
            return CsvParseResult(
                rows=[],
                errors=[
                    CsvParseError(
                        0,
                        "Missing required fields after alias resolution: "
                        + ", ".join(missing)
                        + f". Found headers: {', '.join(raw_fieldnames)}",
                    )
                ],
            )
        logical_to_raw = {
            key: fieldname_by_strip[raw_name]
            for key, raw_name in logical_map.items()
            if raw_name in fieldname_by_strip
        }
        column_strategy = "aliases"

    raw_rows = list(reader)

    def _date_sample(raw_row: dict[str, str | None]) -> str:
        if header_mode == "canonical":
            return (raw_row.get(logical_to_raw["Date"]) or "").strip()
        date_key = logical_to_raw.get("date")
        return (raw_row.get(date_key) or "").strip() if date_key else ""

    date_samples = [_date_sample(r) for r in raw_rows]
    if profile.date_order in {"dmy", "mdy", "ymd"}:
        doc_dates = DocumentDateOrder(order=profile.date_order, assumed=False)  # type: ignore[arg-type]
    else:
        doc_dates = infer_document_date_order(
            date_samples,
            preferred_order=preferred_date_order,
        )

    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    markers: list[CapturedBalanceMarker] = []
    phrases = tuple(profile.balance_marker_phrases)
    txn_row_number = 0

    for index, raw_row in enumerate(raw_rows, start=1):
        try:
            if header_mode == "canonical":
                get_canon = lambda key: (  # noqa: E731
                    raw_row.get(logical_to_raw[key]) or ""
                ).strip()
                description = get_canon("Description")
                amount_raw = get_canon("Amount")
                if is_balance_marker_description(description, phrases) and not positive_money_present(
                    amount_raw, money_format=money_format
                ):
                    txn_date: date | None
                    try:
                        txn_date = parse_statement_date(
                            get_canon("Date"), date_order=doc_dates.order
                        )
                    except ValueError:
                        txn_date = None
                    markers.append(
                        CapturedBalanceMarker(
                            encounter_index=index - 1,
                            txn_date=txn_date,
                            balance=parse_optional_balance(
                                get_canon("Balance") or None, money_format=money_format
                            ),
                            description=description,
                        )
                    )
                    continue
                txn_date = parse_statement_date(
                    get_canon("Date"), date_order=doc_dates.order
                )
                if not description:
                    raise ValueError("Description is required")
                amount = parse_statement_amount(amount_raw, money_format=money_format)
                direction = parse_direction(get_canon("Direction"))
                balance = parse_optional_balance(
                    get_canon("Balance") or None, money_format=money_format
                )
                reference = get_canon("Reference") or None
                txn_row_number += 1
                rows.append(
                    ParsedBankCsvRow(
                        row_number=txn_row_number,
                        txn_date=txn_date,
                        description=description,
                        amount=amount,
                        direction=direction,
                        balance=balance,
                        reference=reference,
                        direction_confidence=DIRECTION_CONFIDENCE_HIGH,
                    )
                )
            else:
                get_logical = lambda key: (  # noqa: E731
                    raw_row.get(logical_to_raw[key]) or ""
                ).strip() if key in logical_to_raw else ""
                description = get_logical("description") or get_logical("reference")
                has_flow = (
                    positive_money_present(get_logical("debit"), money_format=money_format)
                    or positive_money_present(
                        get_logical("credit"), money_format=money_format
                    )
                    or positive_money_present(
                        get_logical("amount"), money_format=money_format
                    )
                )
                if is_balance_marker_description(description, phrases) and not has_flow:
                    try:
                        marker_date = parse_statement_date(
                            get_logical("date"), date_order=doc_dates.order
                        )
                    except ValueError:
                        marker_date = None
                    markers.append(
                        CapturedBalanceMarker(
                            encounter_index=index - 1,
                            txn_date=marker_date,
                            balance=parse_optional_balance(
                                get_logical("balance") or None, money_format=money_format
                            ),
                            description=description or "",
                        )
                    )
                    continue
                txn_date = parse_statement_date(
                    get_logical("date"), date_order=doc_dates.order
                )
                if not description:
                    raise ValueError("Description is required")
                amount, direction = _amount_and_direction_from_row(
                    get_logical=get_logical,
                    money_format=money_format,
                )
                balance = parse_optional_balance(
                    get_logical("balance") or None, money_format=money_format
                )
                reference = get_logical("reference") or None
                txn_row_number += 1
                rows.append(
                    ParsedBankCsvRow(
                        row_number=txn_row_number,
                        txn_date=txn_date,
                        description=description,
                        amount=amount,
                        direction=direction,
                        balance=balance,
                        reference=reference,
                        direction_confidence=(
                            DIRECTION_CONFIDENCE_HIGH if direction else None
                        ),
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

    # Alias path may leave direction empty when only amount+balance — refine like PDF.
    if header_mode == "aliases" and any(not r.direction for r in rows):
        rows, refine_errors = finalize_parsed_rows(
            rows,
            prior_errors=errors,
            reject_on_balance_continuity=False,
            refine_direction_mode=profile.refine_direction_mode,
        )
        errors = refine_errors

    stated_opening, stated_closing = assign_stated_opening_closing(markers, rows)
    rows, stated_errors = apply_stated_balance_continuity(
        rows,
        stated_opening=stated_opening,
        stated_closing=stated_closing,
    )
    errors = list(errors) + stated_errors
    meta = {
        "date_order": doc_dates.order,
        "date_order_assumed": "true" if doc_dates.assumed else "false",
        "parse_profile_id": profile.profile_id,
        "csv_column_strategy": column_strategy,
        "csv_encoding": used_encoding,
    }
    meta.update(stated_balances_to_parse_meta(stated_opening, stated_closing))

    return CsvParseResult(
        rows=rows,
        errors=errors,
        extracted_count=len(rows),
        skipped_line_count=len(markers),
        parse_meta=meta,
    )
