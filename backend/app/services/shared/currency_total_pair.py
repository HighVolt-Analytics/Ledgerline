"""Enforce (currency, total) pairing on multi-currency invoice layouts.

Currency ISO and grand-total amount are often extracted independently. Dual-column
summaries (SGD | USD) then produce mismatches like currency=USD + SGD's total.
This module binds them from document text using explicit tags and column headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from app.services.extraction.field_validators import normalize_amount
from app.services.shared.currency import (
    _ENGLISH_FALSE_POSITIVE_ISO,
    _PREFIXED_SYMBOL_TO_ISO,
)
from app.services.shared.iso4217_catalog import is_iso4217_currency

_EPS = Decimal("0.02")

_MONEY_TOKEN = r"[\d][\d,]*(?:\.\d{1,4})?"

_TOTAL_LABEL = re.compile(
    r"(?is)(?:grand\s+total|amount\s+(?:due|payable)|net\s+payable|"
    r"total\s+(?:due|payable|amount(?:\s+due)?|incl\.?\s*tax|including\s+tax)|"
    r"(?<![a-z])total(?!\s+(?:before|excluding|excl\.?\s*tax|ex\b)|[\s-]*total))"
)

_DUAL_ISO_HEADER = re.compile(
    rf"(?im)(?<![A-Za-z0-9])(?P<c1>[A-Za-z]{{3}})(?![A-Za-z0-9])"
    rf"[^\nA-Za-z0-9]{{1,24}}"
    rf"(?<![A-Za-z0-9])(?P<c2>[A-Za-z]{{3}})(?![A-Za-z0-9])"
)

_TOTAL_LINE_TWO_AMOUNTS = re.compile(
    rf"(?is)(?:grand\s+total|amount\s+(?:due|payable)|net\s+payable|"
    rf"total\s+(?:due|payable|amount(?:\s+due)?)|"
    rf"(?<![a-z])total(?!\s+(?:before|excluding|excl)))"
    rf"[^\d]{{0,64}}"
    rf"(?P<a1>{_MONEY_TOKEN})\s+(?P<a2>{_MONEY_TOKEN})"
)

# FX rate equation fragments must not be treated as payable totals.
# Only the sides of "1 USD = 1.528 AUD" — not "Total USD 720 (at rate …)".
_EQ_BEFORE_AMOUNT = re.compile(r"=\s*$")
_EQ_AFTER_AMOUNT = re.compile(r"^\s*=")
_LEFT_OF_FX_EQ = re.compile(r"(?is)\d(?:[\d,]*(?:\.\d+)?)\s*[A-Za-z]{3}\s*=\s*$")


def _valid_iso(code: str | None) -> str | None:
    token = (code or "").strip().upper()
    if not token or token in _ENGLISH_FALSE_POSITIVE_ISO:
        return None
    if not is_iso4217_currency(token):
        return None
    return token


def _parse_money(token: str | None) -> Decimal | None:
    return normalize_amount(token)


def _amounts_close(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return False
    return (a - b).copy_abs() <= _EPS


@dataclass(frozen=True)
class _TaggedAmount:
    amount: Decimal
    iso: str
    source: str  # "inline_prefix" | "inline_iso" | "column"
    start: int
    end: int


@dataclass(frozen=True)
class CurrencyTotalPairResult:
    currency: str
    total: Decimal | None
    reason: str
    multi_currency: bool = False
    swapped: bool = False


def _prefixed_tagged_amounts(text: str) -> list[_TaggedAmount]:
    out: list[_TaggedAmount] = []
    for prefix, iso in sorted(_PREFIXED_SYMBOL_TO_ISO, key=lambda row: -len(row[0])):
        escaped = re.escape(prefix)
        # US$4,839.60 / US$ 4,839.60
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){escaped}\s*(?P<amt>{_MONEY_TOKEN})",
            re.I,
        )
        for match in pattern.finditer(text):
            money = _parse_money(match.group("amt"))
            if money is None:
                continue
            out.append(
                _TaggedAmount(
                    amount=money,
                    iso=iso,
                    source="inline_prefix",
                    start=match.start(),
                    end=match.end(),
                )
            )
    return out


def _in_fx_rate_context(start: int, end: int, text: str) -> bool:
    before = text[max(0, start - 48) : start]
    after = text[end : min(len(text), end + 16)]
    if _EQ_BEFORE_AMOUNT.search(before):
        return True
    if _LEFT_OF_FX_EQ.search(before):
        return True
    if _EQ_AFTER_AMOUNT.search(after):
        return True
    return False


def _iso_tagged_amounts(text: str) -> list[_TaggedAmount]:
    out: list[_TaggedAmount] = []
    pattern = re.compile(
        rf"(?:"
        rf"(?<![A-Za-z0-9])(?P<code_before>[A-Za-z]{{3}})(?![A-Za-z0-9])\s*"
        rf"(?P<amt_before>{_MONEY_TOKEN})"
        rf"|(?P<amt_after>{_MONEY_TOKEN})\s*"
        rf"(?<![A-Za-z0-9])(?P<code_after>[A-Za-z]{{3}})(?![A-Za-z0-9])"
        rf")"
    )
    for match in pattern.finditer(text):
        if _in_fx_rate_context(match.start(), match.end(), text):
            continue
        code = _valid_iso(match.group("code_before") or match.group("code_after"))
        if not code:
            continue
        money = _parse_money(match.group("amt_before") or match.group("amt_after"))
        if money is None:
            continue
        out.append(
            _TaggedAmount(
                amount=money,
                iso=code,
                source="inline_iso",
                start=match.start(),
                end=match.end(),
            )
        )
    return out


def column_header_isos(text: str | None) -> set[str]:
    """ISO codes that appear as dual-currency column headers (e.g. SGD | USD)."""
    found: set[str] = set()
    for match in _DUAL_ISO_HEADER.finditer(text or ""):
        c1 = _valid_iso(match.group("c1"))
        c2 = _valid_iso(match.group("c2"))
        if c1:
            found.add(c1)
        if c2:
            found.add(c2)
    return found


def iso_appears_as_currency_column(iso: str | None, text: str | None) -> bool:
    code = _valid_iso(iso)
    if not code:
        return False
    return code in column_header_isos(text)


def _column_tagged_amounts(text: str) -> list[_TaggedAmount]:
    """Map dual amounts on a Total line to dual ISO column headers above."""
    out: list[_TaggedAmount] = []
    headers: list[tuple[str, str, int]] = []
    for match in _DUAL_ISO_HEADER.finditer(text):
        c1 = _valid_iso(match.group("c1"))
        c2 = _valid_iso(match.group("c2"))
        if not c1 or not c2 or c1 == c2:
            continue
        headers.append((c1, c2, match.start()))

    if not headers:
        return out

    for match in _TOTAL_LINE_TWO_AMOUNTS.finditer(text):
        a1 = _parse_money(match.group("a1"))
        a2 = _parse_money(match.group("a2"))
        if a1 is None or a2 is None or _amounts_close(a1, a2):
            continue
        # Prefer the nearest dual-currency header before this totals line.
        prior = [h for h in headers if h[2] <= match.start()]
        chosen = prior[-1] if prior else headers[0]
        c1, c2, _ = chosen
        out.append(
            _TaggedAmount(
                amount=a1, iso=c1, source="column", start=match.start("a1"), end=match.end("a1")
            )
        )
        out.append(
            _TaggedAmount(
                amount=a2, iso=c2, source="column", start=match.start("a2"), end=match.end("a2")
            )
        )
    return out


def _near_total_label(pos: int, text: str, *, window: int = 120) -> bool:
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return _TOTAL_LABEL.search(text[start:end]) is not None


def collect_tagged_total_amounts(text: str | None) -> list[_TaggedAmount]:
    """All money amounts with currency affinity, preferring totals-region hits."""
    raw = text or ""
    if not raw.strip():
        return []

    tagged = _prefixed_tagged_amounts(raw) + _iso_tagged_amounts(raw) + _column_tagged_amounts(raw)
    # De-dupe identical (amount, iso, approx span).
    seen: set[tuple[str, str, int]] = set()
    unique: list[_TaggedAmount] = []
    for item in tagged:
        key = (format(item.amount, "f"), item.iso, item.start // 8)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    near_total = [t for t in unique if _near_total_label(t.start, raw)]
    return near_total or unique


def detect_multi_currency_in_text(text: str | None) -> bool:
    """True when ≥2 distinct ISO codes are evidenced next to money amounts."""
    codes = {t.iso for t in collect_tagged_total_amounts(text)}
    if len(codes) >= 2:
        return True
    return len(column_header_isos(text)) >= 2


def _affinity_for_amount(
    amount: Decimal,
    tagged: list[_TaggedAmount],
) -> set[str]:
    return {t.iso for t in tagged if _amounts_close(t.amount, amount)}


def _best_amount_for_iso(
    iso: str,
    tagged: list[_TaggedAmount],
) -> Decimal | None:
    candidates = [t for t in tagged if t.iso == iso]
    if not candidates:
        return None
    # Prefer dual-column totals, then inline tags; among those take max (grand total).
    for source in ("column", "inline_prefix", "inline_iso"):
        pool = [t for t in candidates if t.source == source]
        if pool:
            return max((t.amount for t in pool), key=lambda a: a)
    return max((t.amount for t in candidates), key=lambda a: a)


def _resolve_affinity_mismatch(
    *,
    iso: str,
    total: Decimal,
    owners: set[str],
    tagged: list[_TaggedAmount],
    multi: bool,
) -> CurrencyTotalPairResult:
    """total is tagged to other currency(ies); swap or clear."""
    replacement = _best_amount_for_iso(iso, tagged)
    if replacement is not None and not _amounts_close(replacement, total):
        return CurrencyTotalPairResult(
            currency=iso,
            total=replacement,
            reason=f"swapped_total_to_match_{iso}",
            multi_currency=multi or True,
            swapped=True,
        )
    return CurrencyTotalPairResult(
        currency=iso,
        total=None,
        reason=f"cleared_total_mismatched_affinity_{','.join(sorted(owners))}",
        multi_currency=multi or True,
        swapped=True,
    )


def reconcile_currency_total_pair(
    *,
    currency: str | None,
    total: Decimal | None,
    text: str | None,
) -> CurrencyTotalPairResult:
    """Bind total to the selected currency when multi-currency layout is present.

    Rules:
    - If ``total`` is only evidenced under currency Y and ``currency`` is X≠Y,
      swap ``total`` to the X-tagged amount when available; otherwise clear total.
      This applies even when only one currency has tagged amounts (affinity conflict).
    - Never invent FX; only pick a printed amount tagged for the selected ISO.
    - If currency empty but total is uniquely tagged → fill currency from that tag.
    """
    iso = (currency or "").strip().upper()
    if iso and not is_iso4217_currency(iso):
        iso = ""

    raw = (text or "").strip()
    if not raw:
        return CurrencyTotalPairResult(currency=iso, total=total, reason="no_text")

    tagged = collect_tagged_total_amounts(raw)
    codes = {t.iso for t in tagged}
    multi = len(codes) >= 2 or detect_multi_currency_in_text(raw)

    # Affinity conflict: selected currency disagrees with how the amount is tagged.
    if iso and total is not None:
        owners = _affinity_for_amount(total, tagged)
        if owners and iso not in owners:
            return _resolve_affinity_mismatch(
                iso=iso, total=total, owners=owners, tagged=tagged, multi=multi
            )

    if not multi:
        if not iso and total is not None:
            owners = _affinity_for_amount(total, tagged)
            if len(owners) == 1:
                only = next(iter(owners))
                return CurrencyTotalPairResult(
                    currency=only,
                    total=total,
                    reason=f"filled_currency_from_tagged_total_{only}",
                    multi_currency=False,
                    swapped=False,
                )
        return CurrencyTotalPairResult(
            currency=iso, total=total, reason="single_currency_unchanged", multi_currency=False
        )

    # Multi-currency path.
    if iso and total is not None:
        owners = _affinity_for_amount(total, tagged)
        if iso in owners and len(owners) == 1:
            return CurrencyTotalPairResult(
                currency=iso,
                total=total,
                reason="pair_confirmed",
                multi_currency=True,
            )
        if iso in owners and len(owners) > 1:
            return CurrencyTotalPairResult(
                currency=iso,
                total=total,
                reason="pair_ambiguous_shared_amount",
                multi_currency=True,
            )
        # Total not tagged to any currency — try to find one for selected ISO.
        replacement = _best_amount_for_iso(iso, tagged)
        if replacement is not None and not _amounts_close(replacement, total):
            foreign = [
                t for t in tagged if t.iso != iso and _amounts_close(t.amount, total)
            ]
            if foreign:
                return CurrencyTotalPairResult(
                    currency=iso,
                    total=replacement,
                    reason=f"swapped_total_to_match_{iso}",
                    multi_currency=True,
                    swapped=True,
                )
        return CurrencyTotalPairResult(
            currency=iso,
            total=total,
            reason="multi_currency_total_untagged_keep",
            multi_currency=True,
        )

    if iso and total is None:
        replacement = _best_amount_for_iso(iso, tagged)
        if replacement is not None:
            return CurrencyTotalPairResult(
                currency=iso,
                total=replacement,
                reason=f"filled_total_for_{iso}",
                multi_currency=True,
                swapped=True,
            )
        return CurrencyTotalPairResult(
            currency=iso, total=None, reason="multi_currency_no_total", multi_currency=True
        )

    # Currency empty: if total uniquely tagged, adopt that ISO.
    if total is not None:
        owners = _affinity_for_amount(total, tagged)
        if len(owners) == 1:
            only = next(iter(owners))
            return CurrencyTotalPairResult(
                currency=only,
                total=total,
                reason=f"filled_currency_from_tagged_total_{only}",
                multi_currency=True,
            )
        return CurrencyTotalPairResult(
            currency="",
            total=total,
            reason="multi_currency_currency_uncertain",
            multi_currency=True,
        )

    return CurrencyTotalPairResult(
        currency=iso, total=total, reason="multi_currency_empty", multi_currency=True
    )
