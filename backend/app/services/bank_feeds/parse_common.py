"""Shared parsing helpers for bank statement CSV/PDF imports."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Sequence

from app.models.bank_feed import BankTxnDirection
from app.services.shared.iso4217_catalog import currency_alternation_regex
from app.services.bank_feeds.statement_parse_profile import (
    generic_balance_marker_phrases,
)

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
STATED_OPENING_MISMATCH_MSG = (
    "Stated opening balance does not match balance before first transaction — "
    "rows may be missing from extraction"
)
STATED_CLOSING_MISMATCH_MSG = (
    "Stated closing balance does not match last transaction balance — "
    "rows may be missing from extraction"
)
STATED_OPENING_MISMATCH_NOTE = "stated_opening_balance_mismatch"
STATED_CLOSING_MISMATCH_NOTE = "stated_closing_balance_mismatch"
SKIPPED_LINE_MSG = "Could not parse transaction line"

DirectionConfidence = Literal["high", "medium", "low"]
DIRECTION_CONFIDENCE_HIGH: DirectionConfidence = "high"
DIRECTION_CONFIDENCE_MEDIUM: DirectionConfidence = "medium"
DIRECTION_CONFIDENCE_LOW: DirectionConfidence = "low"

# Phase 1 — extraction provenance (distinct from direction_confidence).
ExtractionConfidence = Literal["high", "medium", "low"]
EXTRACTION_SOURCE_TEXT_FALLBACK_MERGE = "text_fallback_merge"
EXTRACTION_SOURCE_CONTINUATION_MERGE = "continuation_merge"
EXTRACTION_CONFIDENCE_MEDIUM: ExtractionConfidence = "medium"
EXTRACTION_CONFIDENCE_LOW: ExtractionConfidence = "low"
DIRECTION_DISAGREEMENT_NOTE = (
    "direction disagreement between table and text extraction"
)

DateOrder = Literal["dmy", "mdy", "ymd"]
RefineDirectionMode = Literal["only_if_empty", "always", "never"]
# Currencies that commonly use month-first numeric dates when the document is ambiguous.
_MDY_PREFERRED_CURRENCIES = frozenset({"USD"})


@dataclass(frozen=True)
class MoneyFormat:
    """Optional money separators; None fields mean use legacy generic parsing."""

    decimal_separator: str = "."
    thousands_separator: str = ","
    allow_trailing_minus: bool = False

    @classmethod
    def from_profile(cls, profile: Any | None) -> MoneyFormat | None:
        if profile is None:
            return None
        if getattr(profile, "uses_generic_money", False):
            return None  # keep exact pre-Phase-2 parse_money_token path
        return cls(
            decimal_separator=profile.decimal_separator,
            thousands_separator=profile.thousands_separator,
            allow_trailing_minus=bool(getattr(profile, "allow_trailing_minus", False)),
        )

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
    rf"(?:{currency_alternation_regex()}\s*)?"
    r"(?:\$|€|£|₹)?"
    r"[\d,]+\.\d{2}"
    r"\)?$"
)
TRAILING_AMOUNT_RE = re.compile(
    r"(\(?"
    r"(?:Rs\.?\s*)?"
    rf"(?:{currency_alternation_regex()}\s*)?"
    r"(?:\$|€|£|₹)?"
    r"[\d,]+\.\d{2}"
    r"\)?)\s*$"
)
REFERENCE_RE = re.compile(r"\b(REF[\w/-]+)\b", re.IGNORECASE)
SKIP_LINE_RE = re.compile(
    r"^(date\b|transaction\b|statement\b|opening\b|closing\b|page\b|account\b|total\b)",
    re.IGNORECASE,
)
# Boilerplate / footer lines that must not merge into a prior transaction description.
BOILERPLATE_LINE_RE = re.compile(
    r"(?i)^("
    r"continued(\s+on\s+next\s+page)?\b"
    r"|continued\s+from\s+(previous|prior)\b"
    r"|page\s+\d+(\s+of\s+\d+)?"
    r"|please\s+note\b"
    r"|disclaimer\b"
    r"|end\s+of\s+(the\s+)?statement\b"
    r"|this\s+page\b"
    r"|carry\s+forward\b"
    r"|brought\s+forward\b"
    r")\b"
)

# Unambiguous / month-name formats — always tried first regardless of date_order.
_UNAMBIGUOUS_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %b %y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %B %Y",
    "%d %B %y",
)
_DMY_NUMERIC_FORMATS = ("%d/%m/%Y", "%d-%m-%Y")
_MDY_NUMERIC_FORMATS = ("%m/%d/%Y",)
# Back-compat alias: prior unconditional order was unambiguous + DMY then MDY.
_DATE_FORMATS = _UNAMBIGUOUS_DATE_FORMATS + _DMY_NUMERIC_FORMATS + _MDY_NUMERIC_FORMATS

_NUMERIC_DATE_PARTS_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")


@dataclass(frozen=True)
class DocumentDateOrder:
    """Whole-document numeric date order (not decided per row)."""

    order: DateOrder = "dmy"
    assumed: bool = False


@dataclass(frozen=True)
class ParsedBankCsvRow:
    row_number: int
    txn_date: date
    description: str
    amount: Decimal
    direction: str  # debit | credit
    balance: Decimal | None
    reference: str | None
    # high = explicit column/marker; medium = balance-delta; low = weak / continuity conflict
    direction_confidence: DirectionConfidence | None = None
    # Phase 1 provenance — independent of direction_confidence; None = normal path
    extraction_source: str | None = None
    extraction_confidence: ExtractionConfidence | None = None
    # Optional review note from merge (copied to review_flags at import).
    extraction_note: str | None = None


def is_boilerplate_statement_line(text: str) -> bool:
    """True for headers/footers/disclaimers that must not merge into txn descriptions."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return True
    if SKIP_LINE_RE.match(cleaned):
        return True
    if BOILERPLATE_LINE_RE.match(cleaned):
        return True
    # Short all-caps footer-like lines (e.g. "CONFIDENTIAL").
    # Keep lines that contain digits (e.g. "REF 88213 …") — those are often
    # wrapped description continuations, not footers.
    letters = re.sub(r"[^A-Za-z]", "", cleaned)
    if (
        len(letters) >= 5
        and letters.isupper()
        and len(cleaned) <= 48
        and not re.search(r"\d", cleaned)
    ):
        return True
    return False


def normalize_balance_marker_text(text: str) -> str:
    """Lowercase, collapse whitespace, soften punctuation for marker phrase match."""
    cleaned = (text or "").lower().replace("\n", " ").replace("\r", " ")
    cleaned = cleaned.replace("&", " and ")
    # Keep slash for b/f and c/f; turn other punctuation into spaces.
    cleaned = re.sub(r"[^\w\s/]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_balance_marker_description(
    description: str,
    phrases: Sequence[str] | None = None,
) -> bool:
    """True when description equals a known balance-marker phrase (not a substring hit).

    Exact normalized equality avoids swallowing real txns like "BALANCE TRANSFER FEE".
    """
    norm = normalize_balance_marker_text(description)
    if not norm:
        return False
    for phrase in phrases if phrases is not None else generic_balance_marker_phrases():
        if norm == normalize_balance_marker_text(phrase):
            return True
    return False


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

    @property
    def has_low_direction_confidence(self) -> bool:
        return any(
            row.direction_confidence == DIRECTION_CONFIDENCE_LOW for row in self.rows
        )


def preferred_date_order_for_currency(currency: str | None) -> DateOrder | None:
    """Account currency hint when the document's numeric dates are fully ambiguous."""
    if (currency or "").strip().upper() in _MDY_PREFERRED_CURRENCIES:
        return "mdy"
    return None


def _date_formats_for_order(date_order: DateOrder) -> tuple[str, ...]:
    if date_order == "mdy":
        return _UNAMBIGUOUS_DATE_FORMATS + _MDY_NUMERIC_FORMATS + _DMY_NUMERIC_FORMATS
    if date_order == "ymd":
        return ("%Y-%m-%d",) + _UNAMBIGUOUS_DATE_FORMATS[1:] + _DMY_NUMERIC_FORMATS + _MDY_NUMERIC_FORMATS
    # dmy (default / historical behavior)
    return _UNAMBIGUOUS_DATE_FORMATS + _DMY_NUMERIC_FORMATS + _MDY_NUMERIC_FORMATS


def _iter_numeric_date_parts(raw: str) -> Iterable[tuple[int, int]]:
    text = (raw or "").strip()
    if not text:
        return
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    candidates = [text]
    for token in DATE_TOKEN_RE.findall(text):
        candidates.append(token if isinstance(token, str) else token[0])
    seen: set[str] = set()
    for candidate in candidates:
        cand = (candidate or "").strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        match = _NUMERIC_DATE_PARTS_RE.match(cand)
        if match:
            yield int(match.group(1)), int(match.group(2))


def infer_document_date_order(
    raw_date_strings: Iterable[str],
    *,
    preferred_order: DateOrder | None = None,
) -> DocumentDateOrder:
    """Infer DMY vs MDY once for a whole statement from numeric date tokens.

    If any token has first component > 12, MDY is impossible → DMY.
    If any token has second component > 12, DMY is impossible → MDY.
    If still ambiguous, use preferred_order (e.g. from account currency) else DMY,
    and mark ``assumed=True`` for review.
    """
    saw_first_gt_12 = False
    saw_second_gt_12 = False
    for raw in raw_date_strings:
        for first, second in _iter_numeric_date_parts(raw):
            if first > 12:
                saw_first_gt_12 = True
            if second > 12:
                saw_second_gt_12 = True

    if saw_first_gt_12 and not saw_second_gt_12:
        return DocumentDateOrder(order="dmy", assumed=False)
    if saw_second_gt_12 and not saw_first_gt_12:
        return DocumentDateOrder(order="mdy", assumed=False)
    if saw_first_gt_12 and saw_second_gt_12:
        # Conflicting signals in one document — keep historical DMY default, flag assumed.
        return DocumentDateOrder(order="dmy", assumed=True)

    order: DateOrder = preferred_order or "dmy"
    return DocumentDateOrder(order=order, assumed=True)


def collect_date_strings_from_text(text: str) -> list[str]:
    found: list[str] = []
    for line in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if not cleaned:
            continue
        match = DATE_PREFIX_RE.match(cleaned)
        if match:
            found.append(match.group(1))
            continue
        for token in DATE_TOKEN_RE.findall(cleaned):
            found.append(token if isinstance(token, str) else token[0])
    return found


def parse_statement_date(raw: str, *, date_order: DateOrder | None = None) -> date:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Date is required")
    # PDF cells often include newlines or leading dashes ("-\n18 Aug 2026").
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\-\–\—\|•·]+\s*", "", text).strip()

    order: DateOrder = date_order or "dmy"
    formats = _date_formats_for_order(order)

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
        for fmt in formats:
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Unrecognized date format: {raw!r}")


def parse_money_token(
    raw: str,
    *,
    money_format: MoneyFormat | None = None,
) -> tuple[Decimal, str | None]:
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
    text = text.lstrip("$€£₹")

    trailing_minus = False
    if money_format is not None and money_format.allow_trailing_minus and text.endswith("-"):
        trailing_minus = True
        text = text[:-1].strip()

    if money_format is None:
        # Legacy generic path (Phase 0 identical).
        text = text.replace(",", "").replace(" ", "")
    else:
        thousands = money_format.thousands_separator
        decimal = money_format.decimal_separator
        if thousands:
            text = text.replace(thousands, "")
        text = text.replace(" ", "")
        if decimal and decimal != ".":
            if text.count(decimal) > 1:
                raise ValueError(f"Invalid amount: {raw!r}")
            text = text.replace(decimal, ".")

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
    if trailing_minus:
        sign = -1
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {raw!r}") from exc
    value = value.copy_abs() * sign
    if value < 0:
        return value.copy_abs().quantize(Decimal("0.01")), BankTxnDirection.DEBIT.value
    if paren_debit or trailing_minus:
        return value.quantize(Decimal("0.01")), BankTxnDirection.DEBIT.value
    if dir_suffix:
        try:
            return value.quantize(Decimal("0.01")), parse_direction(dir_suffix)
        except ValueError:
            pass
    return value.quantize(Decimal("0.01")), None


def build_trailing_amount_regex(money_format: MoneyFormat | None = None) -> re.Pattern[str]:
    """Trailing amount matcher; generic path keeps module TRAILING_AMOUNT_RE."""
    if money_format is None:
        return TRAILING_AMOUNT_RE
    thousands = re.escape(money_format.thousands_separator)
    decimal = re.escape(money_format.decimal_separator)
    # e.g. 1.234,56 or 1,234.56 with optional trailing minus
    number = rf"[\d{thousands}]+{decimal}\d{{2}}"
    trailing = r"-?" if money_format.allow_trailing_minus else ""
    return re.compile(
        r"(\(?"
        r"(?:Rs\.?\s*)?"
        rf"(?:{currency_alternation_regex()}\s*)?"
        r"(?:\$|€|£|₹)?"
        rf"{number}"
        rf"{trailing}"
        r"\)?)\s*$"
    )


def parse_statement_amount(raw: str, *, money_format: MoneyFormat | None = None) -> Decimal:
    amount, _ = parse_money_token(raw, money_format=money_format)
    return amount


def parse_optional_balance(
    raw: str | None, *, money_format: MoneyFormat | None = None
) -> Decimal | None:
    if not raw:
        return None
    amount, _ = parse_money_token(raw, money_format=money_format)
    return amount


def extract_trailing_amounts(
    text: str,
    *,
    max_amounts: int = 2,
    money_format: MoneyFormat | None = None,
) -> tuple[str, list[_ParsedAmount]]:
    rest = (text or "").strip()
    amounts: list[_ParsedAmount] = []
    trailing_re = build_trailing_amount_regex(money_format)
    while len(amounts) < max_amounts:
        match = trailing_re.search(rest)
        if not match:
            break
        value, direction = parse_money_token(match.group(1), money_format=money_format)
        amounts.insert(0, _ParsedAmount(value, direction))
        rest = rest[: match.start()].strip()
    return rest, amounts


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


def _direction_is_known(direction: str | None) -> bool:
    return (direction or "") in {
        BankTxnDirection.DEBIT.value,
        BankTxnDirection.CREDIT.value,
    }


def refine_row_directions(
    rows: list[ParsedBankCsvRow],
    *,
    mode: RefineDirectionMode = "only_if_empty",
) -> list[ParsedBankCsvRow]:
    """Fill empty directions from balance deltas (default), or always/never per profile.

    ``only_if_empty`` (Phase 0 default): never overwrite explicit debit/credit markers.
    ``always``: restore pre-Phase-0 overwrite from balance deltas — rarely appropriate.
    ``never``: skip balance-delta inference entirely.
    """
    if not rows:
        return rows

    if mode == "never":
        working = list(rows)
        for index, row in enumerate(working):
            if _direction_is_known(row.direction) and row.direction_confidence is None:
                working[index] = replace(
                    row, direction_confidence=DIRECTION_CONFIDENCE_HIGH
                )
        return working

    if mode == "always":
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
            working[index] = replace(
                row,
                direction=direction,
                direction_confidence=(
                    row.direction_confidence
                    if _direction_is_known(row.direction)
                    else DIRECTION_CONFIDENCE_MEDIUM
                )
                or DIRECTION_CONFIDENCE_MEDIUM,
            )
        first = working[0]
        if not _direction_is_known(first.direction) and len(working) >= 2:
            inferred = _infer_first_row_direction_from_second(first, working[1])
            if inferred:
                working[0] = replace(
                    first,
                    direction=inferred,
                    direction_confidence=DIRECTION_CONFIDENCE_MEDIUM,
                )
        elif _direction_is_known(first.direction) and first.direction_confidence is None:
            working[0] = replace(first, direction_confidence=DIRECTION_CONFIDENCE_HIGH)
        return working

    # only_if_empty — Phase 0 behavior (unchanged).
    working = list(rows)
    for index in range(1, len(working)):
        prev = working[index - 1]
        row = working[index]
        if _direction_is_known(row.direction):
            if row.direction_confidence is None:
                working[index] = replace(
                    row, direction_confidence=DIRECTION_CONFIDENCE_HIGH
                )
            continue
        if prev.balance is None or row.balance is None:
            continue
        delta = row.balance - prev.balance
        if delta > 0:
            direction = BankTxnDirection.CREDIT.value
        elif delta < 0:
            direction = BankTxnDirection.DEBIT.value
        else:
            continue
        working[index] = replace(
            row,
            direction=direction,
            direction_confidence=DIRECTION_CONFIDENCE_MEDIUM,
        )

    first = working[0]
    if not _direction_is_known(first.direction) and len(working) >= 2:
        inferred = _infer_first_row_direction_from_second(first, working[1])
        if inferred:
            working[0] = replace(
                first,
                direction=inferred,
                direction_confidence=DIRECTION_CONFIDENCE_MEDIUM,
            )
    elif _direction_is_known(first.direction) and first.direction_confidence is None:
        working[0] = replace(first, direction_confidence=DIRECTION_CONFIDENCE_HIGH)

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


@dataclass(frozen=True)
class CapturedBalanceMarker:
    """No-amount opening/closing / B/F row captured for parse_meta + continuity."""

    encounter_index: int
    txn_date: date | None
    balance: Decimal | None
    description: str


def positive_money_present(
    raw: str | None, *, money_format: MoneyFormat | None = None
) -> bool:
    """True when cell has a parseable amount strictly greater than zero."""
    if not (raw or "").strip():
        return False
    try:
        amount, _ = parse_money_token(raw or "", money_format=money_format)
    except ValueError:
        return False
    return amount > 0


def assign_stated_opening_closing(
    markers: Sequence[CapturedBalanceMarker],
    txn_rows: Sequence[ParsedBankCsvRow],
) -> tuple[Decimal | None, Decimal | None]:
    """Map marker rows to stated opening/closing balances.

    First marker in statement order → opening; last → closing. A single marker is
    tagged by date/order relative to real transactions.
    """
    if not markers:
        return None, None
    if len(markers) >= 2:
        return markers[0].balance, markers[-1].balance

    only = markers[0]
    if not txn_rows:
        return only.balance, None
    first = txn_rows[0]
    last = txn_rows[-1]
    if only.encounter_index == 0:
        return only.balance, None
    if only.txn_date is not None:
        if only.txn_date < first.txn_date:
            return only.balance, None
        if only.txn_date > last.txn_date:
            return None, only.balance
        if only.txn_date == first.txn_date and only.encounter_index <= first.row_number:
            return only.balance, None
        if only.txn_date == last.txn_date:
            return None, only.balance
    return None, only.balance


def inferred_balance_before_txn(row: ParsedBankCsvRow) -> Decimal | None:
    """Reverse-apply amount to running balance to recover prior balance."""
    if row.balance is None:
        return None
    if row.direction == BankTxnDirection.CREDIT.value:
        return (row.balance - row.amount).quantize(Decimal("0.01"))
    if row.direction == BankTxnDirection.DEBIT.value:
        return (row.balance + row.amount).quantize(Decimal("0.01"))
    return None


def apply_stated_balance_continuity(
    rows: list[ParsedBankCsvRow],
    *,
    stated_opening: Decimal | None,
    stated_closing: Decimal | None,
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError]]:
    """Flag mismatches between stated opening/closing and extracted txn balances."""
    if not rows:
        return rows, []
    errors: list[CsvParseError] = []
    annotated = list(rows)

    if stated_opening is not None:
        inferred = inferred_balance_before_txn(rows[0])
        if (
            inferred is not None
            and inferred.quantize(Decimal("0.01"))
            != stated_opening.quantize(Decimal("0.01"))
        ):
            errors.append(
                CsvParseError(
                    row_number=rows[0].row_number,
                    message=(
                        f"{STATED_OPENING_MISMATCH_MSG} "
                        f"(stated {stated_opening:.2f}, inferred {inferred:.2f})"
                    ),
                    raw={
                        "description": rows[0].description,
                        "stated_opening_balance": f"{stated_opening:.2f}",
                        "inferred_opening_balance": f"{inferred:.2f}",
                    },
                )
            )
            first = annotated[0]
            annotated[0] = replace(
                first,
                extraction_confidence=EXTRACTION_CONFIDENCE_LOW,
                extraction_note=STATED_OPENING_MISMATCH_NOTE,
            )

    if stated_closing is not None and rows[-1].balance is not None:
        last_bal = rows[-1].balance.quantize(Decimal("0.01"))
        stated = stated_closing.quantize(Decimal("0.01"))
        if last_bal != stated:
            errors.append(
                CsvParseError(
                    row_number=rows[-1].row_number,
                    message=(
                        f"{STATED_CLOSING_MISMATCH_MSG} "
                        f"(stated {stated_closing:.2f}, got {rows[-1].balance:.2f})"
                    ),
                    raw={
                        "description": rows[-1].description,
                        "stated_closing_balance": f"{stated_closing:.2f}",
                        "last_balance": f"{rows[-1].balance:.2f}",
                    },
                )
            )
            last = annotated[-1]
            annotated[-1] = replace(
                last,
                extraction_confidence=EXTRACTION_CONFIDENCE_LOW,
                extraction_note=STATED_CLOSING_MISMATCH_NOTE,
            )

    return annotated, errors


def stated_balances_to_parse_meta(
    stated_opening: Decimal | None,
    stated_closing: Decimal | None,
) -> dict[str, str]:
    meta: dict[str, str] = {}
    if stated_opening is not None:
        meta["stated_opening_balance"] = f"{stated_opening:.2f}"
    if stated_closing is not None:
        meta["stated_closing_balance"] = f"{stated_closing:.2f}"
    return meta


def validate_balance_continuity(rows: list[ParsedBankCsvRow]) -> list[CsvParseError]:
    """Flag rows where running balance != prior balance ± amount(s).

    Rows with a known amount but no parseable balance stay in the sequence: their
    balance checkpoint is skipped, but their signed amount still applies when the
    next row that *does* have a balance is checked (carry intervening amounts
    forward from the last known balance).
    """
    errors: list[CsvParseError] = []
    last_balance: Decimal | None = None
    pending_delta = Decimal("0.00")

    def _signed_delta(row: ParsedBankCsvRow) -> Decimal | None:
        if row.direction == BankTxnDirection.CREDIT.value:
            return row.amount
        if row.direction == BankTxnDirection.DEBIT.value:
            return -row.amount
        return None

    for row in rows:
        delta = _signed_delta(row)
        if row.balance is None:
            if delta is not None:
                pending_delta += delta
            continue

        if last_balance is not None and delta is not None:
            expected = (last_balance + pending_delta + delta).quantize(Decimal("0.01"))
            got = row.balance.quantize(Decimal("0.01"))
            if expected != got:
                errors.append(
                    CsvParseError(
                        row_number=row.row_number,
                        message=(
                            f"{BALANCE_CONTINUITY_MSG} "
                            f"(expected {expected:.2f}, got {row.balance:.2f})"
                        ),
                        raw={
                            "description": row.description,
                            "prior_balance": f"{last_balance:.2f}",
                            "amount": f"{row.amount:.2f}",
                            "direction": row.direction,
                            **(
                                {"intervening_delta": f"{pending_delta:.2f}"}
                                if pending_delta != 0
                                else {}
                            ),
                        },
                    )
                )

        last_balance = row.balance
        pending_delta = Decimal("0.00")
    return errors


def finalize_parsed_rows(
    rows: list[ParsedBankCsvRow],
    *,
    prior_errors: list[CsvParseError] | None = None,
    reject_on_balance_continuity: bool = True,
    refine_direction_mode: RefineDirectionMode = "only_if_empty",
) -> tuple[list[ParsedBankCsvRow], list[CsvParseError]]:
    """Apply balance-based direction refinement and reject failing rows.

    When ``reject_on_balance_continuity`` is False (typical for PDF table extracts
    where debit/credit columns already supply direction), continuity mismatches are
    reported as warnings but rows are kept — opening-balance gaps are common.

    Balance-delta-inferred rows that fail continuity are marked
    ``direction_confidence=low`` and are never dropped solely for that mismatch
    (review/PARTIAL instead of silent corruption or silent discard).
    """
    refined = refine_row_directions(rows, mode=refine_direction_mode)
    continuity_errors = validate_balance_continuity(refined)
    continuity_numbers = {
        err.row_number for err in continuity_errors if err.row_number > 0
    }

    annotated: list[ParsedBankCsvRow] = []
    for row in refined:
        conf = row.direction_confidence
        if _direction_is_known(row.direction):
            if conf is None:
                conf = DIRECTION_CONFIDENCE_HIGH
            if (
                row.row_number in continuity_numbers
                and conf == DIRECTION_CONFIDENCE_MEDIUM
            ):
                conf = DIRECTION_CONFIDENCE_LOW
        else:
            conf = DIRECTION_CONFIDENCE_LOW
        annotated.append(
            row
            if row.direction_confidence == conf
            else replace(row, direction_confidence=conf)
        )

    direction_errors = validate_row_directions(annotated)
    reject_numbers = {err.row_number for err in direction_errors if err.row_number > 0}
    if reject_on_balance_continuity:
        for err in continuity_errors:
            if err.row_number <= 0:
                continue
            # Keep low-confidence (balance-inferred + mismatch) for review.
            match = next((r for r in annotated if r.row_number == err.row_number), None)
            if match is not None and match.direction_confidence == DIRECTION_CONFIDENCE_LOW:
                continue
            reject_numbers.add(err.row_number)

    accepted = [row for row in annotated if row.row_number not in reject_numbers]
    errors = list(prior_errors or [])
    errors.extend(direction_errors)
    errors.extend(continuity_errors)
    return accepted, errors


def parse_statement_text_line(
    line: str,
    *,
    row_number: int,
    date_order: DateOrder | None = None,
    money_format: MoneyFormat | None = None,
) -> ParsedBankCsvRow | None:
    cleaned = re.sub(r"\s+", " ", (line or "").strip())
    if not cleaned or SKIP_LINE_RE.match(cleaned):
        return None

    date_match = DATE_PREFIX_RE.match(cleaned)
    if not date_match:
        return None

    txn_date = parse_statement_date(date_match.group(1), date_order=date_order)
    rest = cleaned[date_match.end() :].strip()
    rest, trailing_reference = _strip_trailing_reference_token(rest)
    original_rest = rest
    rest = _normalize_inline_directions(rest)

    body, amount_parts = extract_trailing_amounts(rest, money_format=money_format)
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
    confidence: DirectionConfidence | None = (
        DIRECTION_CONFIDENCE_HIGH if _direction_is_known(direction) else None
    )
    return ParsedBankCsvRow(
        row_number=row_number,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        balance=balance,
        reference=reference,
        direction_confidence=confidence,
    )


def parse_statement_text_block(
    text: str,
    *,
    preferred_date_order: DateOrder | None = None,
    date_order: DocumentDateOrder | None = None,
    money_format: MoneyFormat | None = None,
    refine_direction_mode: RefineDirectionMode = "only_if_empty",
) -> CsvParseResult:
    rows: list[ParsedBankCsvRow] = []
    errors: list[CsvParseError] = []
    candidate_line_count = 0
    skipped_line_count = 0
    row_number = 0

    doc_dates = date_order or infer_document_date_order(
        collect_date_strings_from_text(text),
        preferred_order=preferred_date_order,
    )

    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if not cleaned:
            continue
        if is_boilerplate_statement_line(cleaned):
            continue
        if not DATE_PREFIX_RE.match(cleaned):
            # Phase 1.2 — wrap continuation into prior txn description.
            if rows:
                prev = rows[-1]
                rows[-1] = replace(
                    prev,
                    description=f"{prev.description} {cleaned}".strip(),
                    extraction_source=EXTRACTION_SOURCE_CONTINUATION_MERGE,
                    extraction_confidence=EXTRACTION_CONFIDENCE_MEDIUM,
                )
            continue

        candidate_line_count += 1
        row_number += 1
        try:
            parsed = parse_statement_text_line(
                cleaned,
                row_number=row_number,
                date_order=doc_dates.order,
                money_format=money_format,
            )
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

    accepted, all_errors = finalize_parsed_rows(
        rows,
        prior_errors=errors,
        refine_direction_mode=refine_direction_mode,
    )
    meta = {
        "extraction_method": "text",
        "date_order": doc_dates.order,
        "date_order_assumed": "true" if doc_dates.assumed else "false",
    }
    return CsvParseResult(
        rows=accepted,
        errors=all_errors,
        extracted_count=len(accepted),
        candidate_line_count=candidate_line_count,
        skipped_line_count=skipped_line_count,
        parse_meta=meta,
    )
