"""Shared parsing helpers for bank statement CSV/PDF imports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.bank_feed import BankTxnDirection
from app.services.shared.iso4217_catalog import currency_alternation_regex

DIRECTION_UNCERTAIN_IMPORT_MSG = (
    "Couldn't determine transaction direction from this PDF layout. "
    "Please export CSV from your bank instead."
)
DIRECTION_UNCERTAIN_ROW_MSG = (
    "Couldn't determine transaction direction for this line. "
    "Export CSV from your bank if this statement layout isn't supported."
)
BALANCE_CONTINUITY_MSG = (
    "Running balance does not match prior balance ± amount — row may be misparsed"
)
SKIPPED_LINE_MSG = "Could not parse transaction line"

# Leading date on a statement line (numeric + month-name variants).
DATE_PREFIX_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
    re.IGNORECASE,
)
# Same patterns anywhere in a cell (PDF multi-line / junk-prefixed dates).
DATE_TOKEN_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
    re.IGNORECASE,
)

MONEY_TOKEN_RE = re.compile(
    r"^\(?"
    r"(?:Rs\.?\s*)?"
    r"(?:[A-Z]{3}\s*)?"
    r"(?:\$|€|£|₹)?"
    r"[\d,]+\.\d{2}"
    r"\)?$"
)
TRAILING_AMOUNT_RE = re.compile(
    r"(\(?"
    r"(?:Rs\.?\s*)?"
    r"(?:[A-Z]{3}\s*)?"
    r"(?:\$|€|£|₹)?"
    r"[\d,]+\.\d{2}"
    r"\)?)\s*$"
)
REFERENCE_RE = re.compile(r"\b(REF[\w/-]+)\b", re.IGNORECASE)
SKIP_LINE_RE = re.compile(
    r"^(date\b|transaction\b|statement\b|opening\b|closing\b|page\b|account\b|total\b)",
    re.IGNORECASE,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %b %y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %B %Y",
    "%d %B %y",
)


@dataclass(frozen=True)
class ParsedBankCsvRow:
    row_number: int
    txn_date: date
    description: str
    amount: Decimal
    direction: str  # debit | credit
    balance: Decimal | None
    reference: str | None


@dataclass(frozen=True)
class CsvParseError:
    row_number: int
    message: str
    raw: dict[str, str] | None = None


@dataclass
class CsvParseResult:
    rows: list[ParsedBankCsvRow]
    errors: list[CsvParseError]
    extracted_count: int = 0
    candidate_line_count: int = 0
    skipped_line_count: int = 0
    parse_meta: dict[str, str] = field(default_factory=dict)


def parse_statement_date(raw: str) -> date:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Date is required")
    # PDF cells often include newlines or leading dashes ("-\n18 Aug 2026").
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\-\–\—\|•·]+\s*", "", text).strip()

    candidates = [text]
    tokens = DATE_TOKEN_RE.findall(text)
    for token in tokens:
        candidates.append(token if isinstance(token, str) else token[0])

    seen: set[str] = set()
    for candidate in candidates:
        cand = (candidate or "").strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Unrecognized date format: {raw!r}")


def parse_money_token(raw: str) -> tuple[Decimal, str | None]:
    """Parse a monetary token; parentheses imply debit (money out)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Amount is required")
    # Flatten PDF cell noise
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    paren_debit = text.startswith("(") and text.endswith(")")
    if paren_debit:
        text = text[1:-1].strip()
    text = re.sub(
        rf"^(?:Rs\.?|{currency_alternation_regex()})\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.lstrip("$€£₹").replace(",", "").replace(" ", "")
    # CR/DR suffixes sometimes trail the amount in a single cell
    dir_suffix = None
    suffix_m = re.search(r"(?i)(cr|dr|credit|debit)$", text)
    if suffix_m:
        dir_suffix = suffix_m.group(1)
        text = text[: suffix_m.start()].strip()
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw!r}") from exc
    value = value.copy_abs() * sign
    if value < 0:
        return value.copy_abs().quantize(Decimal("0.01")), BankTxnDirection.DEBIT.value
    if paren_debit:
        return value.quantize(Decimal("0.01")), BankTxnDirection.DEBIT.value
    if dir_suffix:
        try:
            return value.quantize(Decimal("0.01")), parse_direction(dir_suffix)
        except ValueError:
            pass
    return value.quantize(Decimal("0.01")), None


def parse_statement_amount(raw: str) -> Decimal:
    amount, _ = parse_money_token(raw)
    return amount


def parse_optional_balance(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    amount, _ = parse_money_token(raw)
    return amount


def parse_direction(raw: str) -> str:
    text = (raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    if text in {
        "in",
        "credit",
        "cr",
        "money_in",
        "money in",
        "deposit",
        "deposits",
        "received",
        "receipt",
        "receipts",
        "inflow",
        "inflows",
        "paid in",
        "credit amount",
    }:
        return BankTxnDirection.CREDIT.value
    if text in {
        "out",
        "debit",
        "dr",
        "money_out",
        "money out",
        "withdrawal",
        "withdrawals",
        "payment",
        "payments",
        "paid",
        "paid out",
        "outflow",
        "outflows",
        "debit amount",
    }:
        return BankTxnDirection.DEBIT.value
    raise ValueError(f"Direction must be in/out (or credit/debit); got {raw!r}")


@dataclass(frozen=True)
class _ParsedAmount:
    value: Decimal
    direction: str | None = None


def extract_trailing_amounts(text: str, *, max_amounts: int = 2) -> tuple[str, list[_ParsedAmount]]:
    rest = (text or "").strip()
    amounts: list[_ParsedAmount] = []
    while len(amounts) < max_amounts:
        match = TRAILING_AMOUNT_RE.search(rest)
        if not match:
            break
        value, direction = parse_money_token(match.group(1))
        amounts.insert(0, _ParsedAmount(value, direction))
        rest = rest[: match.start()].strip()
    return rest, amounts


def extract_reference(description: str) -> str | None:
    match = REFERENCE_RE.search(description or "")
    return match.group(1) if match else None


def _normalize_inline_directions(text: str) -> str:
    return re.sub(
        r"([\d,]+\.\d{2}|\([\d,]+\.\d{2}\))\s+"
        r"(dr|cr|debit|credit|out|in|withdrawal|deposit)\s+"
        r"(?=[\d,]+\.\d{2}|\([\d,]+\.\d{2}\))",
        r"\1 ",
        text or "",
        flags=re.IGNORECASE,
    )


def _strip_trailing_reference_token(text: str) -> tuple[str, str | None]:
    match = re.search(r"\s+(REF[\w/-]+)\s*$", text or "", re.IGNORECASE)
    if match:
        return text[: match.start()].strip(), match.group(1)
    return text, None


def _direction_between_amount_and_balance(text: str) -> str | None:
    """Direction token between txn amount and running balance at end of line."""
    match = re.search(
        r"([\d,]+\.\d{2}|\([\d,]+\.\d{2}\))\s+"
        r"(dr|cr|debit|credit|out|in|withdrawal|deposit)\s+"
        r"([\d,]+\.\d{2}|\([\d,]+\.\d{2}\))\s*$",
        text or "",
        re.IGNORECASE,
    )
    if match:
        return parse_direction(match.group(2))
    return None


def _direction_after_amount_at_end(text: str) -> str | None:
    """Direction token immediately after txn amount when balance column is absent."""
    match = re.search(
        r"([\d,]+\.\d{2}|\([\d,]+\.\d{2}\))\s+"
        r"(dr|cr|debit|credit|out|in|withdrawal|deposit)\s*$",
        text or "",
        re.IGNORECASE,
    )
    if match:
        return parse_direction(match.group(2))
    return None


def _resolve_inline_direction(original_rest: str) -> str | None:
    return _direction_between_amount_and_balance(
        original_rest
    ) or _direction_after_amount_at_end(original_rest)


# Suffix-only direction tokens — exclude in/cr/dr (common inside UPI/NEFT narration).
_SUFFIX_DIRECTION_RE = re.compile(
    r"\s+\b(out|debit|credit|withdrawal|deposit|payment|paid)\s*$",
    re.IGNORECASE,
)


def _pop_trailing_direction(text: str) -> tuple[str, str | None]:
    match = _SUFFIX_DIRECTION_RE.search(text or "")
    if not match:
        return text, None
    return text[: match.start()].strip(), parse_direction(match.group(1))


def _infer_first_row_direction_from_second(
    first: ParsedBankCsvRow, second: ParsedBankCsvRow
) -> str | None:
    if first.balance is None or second.balance is None:
        return None
    if second.direction == BankTxnDirection.CREDIT.value:
        if first.balance == second.balance - second.amount:
            return BankTxnDirection.DEBIT.value
    if second.direction == BankTxnDirection.DEBIT.value:
        if first.balance == second.balance + second.amount:
            return BankTxnDirection.CREDIT.value
    return None


def refine_row_directions(rows: list[ParsedBankCsvRow]) -> list[ParsedBankCsvRow]:
    """Direction from balance deltas only — never keyword/description guessing."""
    if not rows:
        return rows

    working: list[ParsedBankCsvRow] = list(rows)
    for index in range(1, len(working)):
        prev = working[index - 1]
        row = working[index]
        if prev.balance is None or row.balance is None:
            continue
        delta = row.balance - prev.balance
        if delta > 0:
            direction = BankTxnDirection.CREDIT.value
        elif delta < 0:
            direction = BankTxnDirection.DEBIT.value
        else:
            direction = row.direction
        working[index] = ParsedBankCsvRow(
            row_number=row.row_number,
            txn_date=row.txn_date,
            description=row.description,
            amount=row.amount,
            direction=direction,
            balance=row.balance,
            reference=row.reference,
        )

    first = working[0]
    if not first.direction and len(working) >= 2:
        inferred = _infer_first_row_direction_from_second(first, working[1])
        if inferred:
            working[0] = ParsedBankCsvRow(
                row_number=first.row_number,
                txn_date=first.txn_date,
                description=first.description,
                amount=first.amount,
                direction=inferred,
                balance=first.balance,
                reference=first.reference,
            )

    return working


def validate_row_directions(rows: list[ParsedBankCsvRow]) -> list[CsvParseError]:
    errors: list[CsvParseError] = []
    for row in rows:
        if row.direction not in {BankTxnDirection.DEBIT.value, BankTxnDirection.CREDIT.value}:
            errors.append(
                CsvParseError(
                    row_number=row.row_number,
                    message=DIRECTION_UNCERTAIN_ROW_MSG,
                    raw={"description": row.description},
                )
            )
    return errors


def validate_balance_continuity(rows: list[ParsedBankCsvRow]) -> list[CsvParseError]:
    """Flag rows where running balance != prior balance ± amount."""
    errors: list[CsvParseError] = []
    prev: ParsedBankCsvRow | None = None
    for row in rows:
        if prev is None or prev.balance is None or row.balance is None:
            prev = row
            continue
        if row.direction == BankTxnDirection.CREDIT.value:
            expected = prev.balance + row.amount
        else:
            expected = prev.balance - row.amount
        if expected.quantize(Decimal("0.01")) != row.balance.quantize(Decimal("0.01")):
            errors.append(
                CsvParseError(
                    row_number=row.row_number,
                    message=(
                        f"{BALANCE_CONTINUITY_MSG} "
                        f"(expected {expected:.2f}, got {row.balance:.2f})"
                    ),
                    raw={
                        "description": row.description,
                        "prior_balance": f"{prev.balance:.2f}",
                        "amount": f"{row.amount:.2f}",
                        "direction": row.direction,
                    },
                )
            )
        prev = row
    return errors


def finalize_parsed_rows(
    rows: list[ParsedBankCsvRow],
    *,
    prior_errors: list[CsvParseError] | None = None,
    reject_on_balance_continuity: bool = True,
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError]]:
    """Apply balance-based direction refinement and reject failing rows.

    When ``reject_on_balance_continuity`` is False (typical for PDF table extracts
    where debit/credit columns already supply direction), continuity mismatches are
    reported as warnings but rows are kept — opening-balance gaps are common.
    """
    refined = refine_row_directions(rows)
    direction_errors = validate_row_directions(refined)
    continuity_errors = validate_balance_continuity(refined)
    reject_numbers = {err.row_number for err in direction_errors if err.row_number > 0}
    if reject_on_balance_continuity:
        reject_numbers |= {
            err.row_number for err in continuity_errors if err.row_number > 0
        }
    accepted = [row for row in refined if row.row_number not in reject_numbers]
    errors = list(prior_errors or [])
    errors.extend(direction_errors)
    errors.extend(continuity_errors)
    return accepted, errors


def parse_statement_text_line(line: str, *, row_number: int) -> ParsedBankCsvRow | None:
    cleaned = re.sub(r"\s+", " ", (line or "").strip())
    if not cleaned or SKIP_LINE_RE.match(cleaned):
        return None

    date_match = DATE_PREFIX_RE.match(cleaned)
    if not date_match:
        return None

    txn_date = parse_statement_date(date_match.group(1))
    rest = cleaned[date_match.end() :].strip()
    rest, trailing_reference = _strip_trailing_reference_token(rest)
    original_rest = rest
    rest = _normalize_inline_directions(rest)

    body, amount_parts = extract_trailing_amounts(rest)
    if not amount_parts:
        return None

    flow_direction = _resolve_inline_direction(original_rest)
    body, suffix_direction = _pop_trailing_direction(body)
    inline_direction = flow_direction or suffix_direction

    txn_amount = amount_parts[0] if len(amount_parts) == 1 else amount_parts[-2]
    balance_part = amount_parts[-1] if len(amount_parts) >= 2 else None
    amount = txn_amount.value
    balance = balance_part.value if balance_part else None
    signed_direction = txn_amount.direction

    description = body.strip() or "Bank transaction"
    reference = trailing_reference or extract_reference(description)

    direction = signed_direction or inline_direction or ""
    return ParsedBankCsvRow(
        row_number=row_number,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        balance=balance,
        reference=reference,
    )


def parse_statement_text_block(text: str) -> CsvParseResult:
    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    candidate_line_count = 0
    skipped_line_count = 0
    row_number = 0

    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if not cleaned:
            continue
        if SKIP_LINE_RE.match(cleaned):
            continue
        if not DATE_PREFIX_RE.match(cleaned):
            continue

        candidate_line_count += 1
        row_number += 1
        try:
            parsed = parse_statement_text_line(cleaned, row_number=row_number)
            if parsed is None:
                skipped_line_count += 1
                errors.append(
                    CsvParseError(
                        row_number=row_number,
                        message=SKIPPED_LINE_MSG,
                        raw={"line": cleaned},
                    )
                )
                continue
            rows.append(parsed)
        except ValueError as exc:
            errors.append(
                CsvParseError(row_number=row_number, message=str(exc), raw={"line": cleaned})
            )

    accepted, all_errors = finalize_parsed_rows(rows, prior_errors=errors)
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate_line_count,
        skipped_line_count=skipped_line_count,
        parse_meta={"extraction_method": "text"},
    )
