"""Normalize bank narration text and compute import fingerprints."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

# Strip punctuation entirely (do not replace with spaces) so bank narrations like
# "INV1042" match invoice refs like "INV-1042" / "INV_1042" / "INV.1042" / "INV/1042".
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")
# Party-name only (S_ref) — not used in fingerprints (would rewrite import hashes).
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:ltd|limited|inc|incorporated|corp|corporation|plc|llc|llp|"
    r"pvt|private|co|company|gmbh|sarl|bv|nv|pty|proprietary)\b",
    re.IGNORECASE,
)


def normalize_description(raw: str) -> str:
    """Trim, lowercase, strip punctuation, collapse whitespace.

    Punctuation is removed (not replaced with spaces) so hyphenated invoice
    numbers align with bank narrations that drop separators. Payment-rail
    prefixes (UPI/NEFT/IMPS/…) are preserved — they distinguish otherwise
    identical lines for fingerprint de-dupe. Does **not** strip legal suffixes
    (Ltd/Inc/…) — those are for party-name matching only.
    """
    text = (raw or "").strip().lower()
    text = _NON_ALNUM_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def normalize_party_name(raw: str) -> str:
    """Party name for S_ref: same as description normalize, then drop legal suffixes."""
    text = normalize_description(raw)
    text = _LEGAL_SUFFIX_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def compute_fingerprint(
    *,
    txn_date: date,
    amount: Decimal,
    direction: str,
    description_normalized: str,
) -> str:
    """SHA-256 hex of normalized date|amount|direction|description (not raw text)."""
    amt = f"{Decimal(amount).quantize(Decimal('0.01')):.2f}"
    payload = "|".join(
        [
            txn_date.isoformat(),
            amt,
            (direction or "").strip().lower(),
            description_normalized or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
