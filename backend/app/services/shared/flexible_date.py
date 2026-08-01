"""Locale-flexible date parsing for document extraction."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

DateOrder = Literal["DMY", "MDY", "YMD"]

_NUMERIC_FORMATS_DMY: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
)

_NUMERIC_FORMATS_MDY: tuple[str, ...] = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m.%d.%Y",
    "%Y/%m/%d",
)

_NAME_FORMATS: tuple[str, ...] = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%b %d,%Y",
    "%B %d,%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%d %b, %Y",
    "%d %B, %Y",
)

_ISO_DATETIME_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:[T\s]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$",
    re.I,
)
_COMPACT_YMD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

_DATE_LABEL_PREFIX = re.compile(
    r"(?is)^(?:"
    r"date[ \t]+of[ \t]+issue|issued[ \t]+on|invoice[ \t]+date|tax[ \t]+invoice[ \t]+date|"
    r"document[ \t]+date|billing[ \t]+date|dated|date"
    r")[ \t]*(?:is|:)?[ \t]*",
)

_EXCLUDED_DATE_LABEL = re.compile(
    r"(?i)(?:validity|due|delivery|ship(?:ping)?|expir|payment|maturity)"
)

_INVOICE_DATE_LINE = re.compile(
    r"(?im)"
    r"(?:"
    r"(?<![a-z])invoice[ \t]+date|"
    r"tax[ \t]+invoice[ \t]+date|"
    r"date[ \t]+of[ \t]+issue|"
    r"issued[ \t]+on|"
    r"document[ \t]+date|"
    r"billing[ \t]+date|"
    r"claim[ \t]+date|"
    r"settlement[ \t]+date|"
    r"request[ \t]+date|"
    r"expense[ \t]+date|"
    r"dated"
    r")"
    r"(?:[ \t]*(?:is|:))?[ \t]*"
    r"(?P<value>[^\n\r]{4,40})"
)

_GENERIC_DATE_LINE = re.compile(
    r"(?im)(?<![a-z])(?P<label>date)[ \t]*:[ \t]*(?P<value>[^\n\r]{4,24})"
)

# TE / internal forms: header row "CLAIM NO. DATE" then value row "EXP-… 3 June 2026".
_FORM_NO_DATE_HEADER = re.compile(
    r"(?is)\b(?:claim|settlement|request|advance|document|invoice)\s+no\.?\b"
    r"[^\n]{0,48}\bdate\b\s*\n(?P<body>[^\n\r]{4,96})"
)
_DATE_TOKEN_IN_LINE = re.compile(
    r"(?i)(?P<value>"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")"
)


def _clean_date_token(raw: str) -> str:
    token = (raw or "").strip()
    token = re.sub(r"\s+", " ", token)
    token = token.rstrip(".,;")
    return token.strip()


def strip_date_label_prefix(raw: str) -> str:
    """Remove common issuance-date label prefixes from a date token."""
    token = _clean_date_token(raw)
    if not token:
        return ""
    stripped = _DATE_LABEL_PREFIX.sub("", token).strip()
    return stripped or token


def parse_flexible_date(
    raw: str | None,
    *,
    date_order: DateOrder = "DMY",
) -> date | None:
    """Parse common invoice date strings (AU, US, ISO, month names)."""
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()

    token = strip_date_label_prefix(str(raw))
    if not token:
        return None

    iso_match = _ISO_DATETIME_PREFIX.match(token)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass

    compact = _COMPACT_YMD.match(re.sub(r"\s+", "", token))
    if compact:
        try:
            return date(int(compact.group(1)), int(compact.group(2)), int(compact.group(3)))
        except ValueError:
            pass

    numeric = _NUMERIC_FORMATS_MDY if date_order == "MDY" else _NUMERIC_FORMATS_DMY
    if date_order == "YMD":
        numeric = ("%Y-%m-%d", "%Y/%m/%d")

    for fmt in (*numeric, *_NAME_FORMATS):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue

    # Ambiguous slash dates: try alternate order when first pass fails.
    if date_order == "DMY" and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", token):
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue
    if date_order == "MDY" and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", token):
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue

    return None


def date_ocr_match_tokens(value: date) -> tuple[str, ...]:
    """Build common OCR renderings for grounding a parsed date."""
    d, m, y = value.day, value.month, value.year
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        clean = token.strip()
        if clean and clean not in seen:
            seen.add(clean)
            tokens.append(clean)

    for fmt in _NUMERIC_FORMATS_DMY + _NUMERIC_FORMATS_MDY + _NAME_FORMATS:
        try:
            _add(value.strftime(fmt))
        except ValueError:
            continue

    # strftime %d is zero-padded; forms/OCR often print "3 June 2026".
    mon_abbr = value.strftime("%b")
    mon_full = value.strftime("%B")
    _add(f"{d} {mon_abbr} {y}")
    _add(f"{d} {mon_full} {y}")
    _add(f"{mon_abbr} {d}, {y}")
    _add(f"{mon_full} {d}, {y}")
    _add(f"{mon_abbr} {d} {y}")
    _add(f"{mon_full} {d} {y}")
    _add(f"{d}-{mon_abbr}-{y}")
    _add(f"{d}-{mon_full}-{y}")

    _add(f"{d}/{m}/{y}")
    _add(f"{m}/{d}/{y}")
    _add(f"{d}-{m}-{y}")
    _add(f"{m}-{d}-{y}")
    _add(f"{d}.{m}.{y}")
    _add(f"{d:02d}/{m:02d}/{y}")
    _add(f"{m:02d}/{d:02d}/{y}")
    _add(f"{d:02d}-{m:02d}-{y}")
    _add(f"{m:02d}-{d:02d}-{y}")
    _add(f"{y}{m:02d}{d:02d}")
    _add(f"{y}-{m:02d}-{d:02d}")
    return tuple(tokens)


def recover_labeled_invoice_date_from_text(
    text: str | None,
    *,
    date_order: DateOrder = "DMY",
) -> date | None:
    """Recover issuance date from labeled lines in PDF/OCR text."""
    if not (text or "").strip():
        return None

    for match in _INVOICE_DATE_LINE.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 40) : match.start()]
        if _EXCLUDED_DATE_LABEL.search(prefix):
            continue
        parsed = parse_flexible_date(match.group("value"), date_order=date_order)
        if parsed is not None:
            return parsed

    for match in _GENERIC_DATE_LINE.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 40) : match.start()]
        if _EXCLUDED_DATE_LABEL.search(prefix):
            continue
        parsed = parse_flexible_date(match.group("value"), date_order=date_order)
        if parsed is not None:
            return parsed

    # Internal claim/settlement forms put DATE as a column header, not "Date:".
    for match in _FORM_NO_DATE_HEADER.finditer(text or ""):
        body = match.group("body") or ""
        token_match = _DATE_TOKEN_IN_LINE.search(body)
        if not token_match:
            continue
        parsed = parse_flexible_date(token_match.group("value"), date_order=date_order)
        if parsed is not None:
            return parsed

    return None
