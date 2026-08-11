"""Application-level OCR text integrity signals.

Detects corrupted OCR that is long enough to pass sparse/short gates but is
unusable for grounding (classic case: non-Latin scripts misread as Greek /
script soup). Used across vision grounding, vendor plausibility, and quality
gates — not document-specific.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

# Scripts that commonly appear as OCR misreads of other writing systems.
_MISREAD_SCRIPTS = frozenset({"GREEK", "COPTIC"})

# Scripts that are themselves legitimate primary document scripts.
_NATIVE_DOCUMENT_SCRIPTS = frozenset(
    {
        "LATIN",
        "COMMON",
        "INHERITED",
        "HAN",
        "HIRAGANA",
        "KATAKANA",
        "HANGUL",
        "ARABIC",
        "DEVANAGARI",
        "BENGALI",
        "GUJARATI",
        "GURMUKHI",
        "TAMIL",
        "TELUGU",
        "KANNADA",
        "MALAYALAM",
        "THAI",
        "LAO",
        "MYANMAR",
        "KHMER",
        "TIBETAN",
        "HEBREW",
        "CYRILLIC",
        "ETHIOPIC",
        "GEORGIAN",
        "ARMENIAN",
    }
)

_MOJIBAKE_MARKERS = re.compile(
    r"(?:Ã.|Â.|â€|ï¿½|\ufffd|\\u00[0-9a-f]{2})",
    re.I,
)


def document_handwriting_likely(payload: dict[str, Any]) -> bool:
    """Heuristic: high confidence variance across words suggests handwriting."""
    words = payload.get("ocr_words")
    if not isinstance(words, list) or len(words) < 5:
        return False
    scores: list[float] = []
    for row in words:
        if not isinstance(row, dict):
            continue
        try:
            scores.append(float(row.get("confidence", 0)))
        except (TypeError, ValueError):
            continue
    if len(scores) < 5:
        return False
    avg = sum(scores) / len(scores)
    variance = sum((s - avg) ** 2 for s in scores) / len(scores)
    return variance > 0.08 and avg < 0.85


def _script_name(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch, "")
    except ValueError:
        return None
    if not name:
        return None
    # e.g. "GREEK CAPITAL LETTER ALPHA" → GREEK; "CJK UNIFIED IDEOGRAPH-..." → HAN
    if name.startswith("CJK "):
        return "HAN"
    token = name.split(" ", 1)[0]
    return token or None


def count_letter_scripts(text: str | None) -> Counter[str]:
    """Count alphabetic characters by Unicode script family."""
    counts: Counter[str] = Counter()
    for ch in text or "":
        script = _script_name(ch)
        if script:
            counts[script] += 1
    return counts


def ocr_text_corruption_signals(text: str | None) -> dict[str, Any]:
    """Return diagnostic signals for OCR text integrity (empty when text thin)."""
    body = (text or "").strip()
    letters = count_letter_scripts(body)
    total_letters = sum(letters.values())
    detail: dict[str, Any] = {
        "text_chars": len(body),
        "letter_count": total_letters,
        "script_counts": dict(letters),
        "corrupted": False,
        "reasons": [],
    }
    if total_letters < 12:
        detail["reasons"].append("too_few_letters")
        return detail

    misread = sum(letters[s] for s in _MISREAD_SCRIPTS if s in letters)
    misread_ratio = misread / total_letters if total_letters else 0.0
    latin = letters.get("LATIN", 0)
    native_non_latin = sum(
        count
        for script, count in letters.items()
        if script not in {"LATIN", "COMMON", "INHERITED"} | _MISREAD_SCRIPTS
        and script in _NATIVE_DOCUMENT_SCRIPTS
    )

    # Classic OCR failure: substantial Greek (etc.) with little true native script.
    if misread_ratio >= 0.18 and native_non_latin < max(4, total_letters * 0.05):
        detail["corrupted"] = True
        detail["reasons"].append("misread_script_dominant")
        detail["misread_ratio"] = round(misread_ratio, 3)

    # Script soup: many scripts, none dominant, plus misread present.
    distinct = {s for s, n in letters.items() if n >= 3 and s not in {"COMMON", "INHERITED"}}
    if len(distinct) >= 4 and misread >= 6 and latin >= 6:
        top = letters.most_common(1)[0][1] if letters else 0
        if top / total_letters < 0.55:
            detail["corrupted"] = True
            if "script_soup" not in detail["reasons"]:
                detail["reasons"].append("script_soup")

    if _MOJIBAKE_MARKERS.search(body):
        detail["corrupted"] = True
        detail["reasons"].append("mojibake_markers")

    return detail


def ocr_text_looks_corrupted(text: str | None) -> bool:
    """True when OCR text is long but unusable for field grounding / vendor extract."""
    return bool(ocr_text_corruption_signals(text).get("corrupted"))


def vendor_name_looks_ocr_garbage(value: str | None) -> bool:
    """True when a vendor candidate is itself script-garbage (not a real name)."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) < 3:
        return False
    letters = count_letter_scripts(text)
    total = sum(letters.values())
    if total < 3:
        return False
    misread = sum(letters[s] for s in _MISREAD_SCRIPTS if s in letters)
    if misread / total >= 0.35:
        return True
    # Mixed punctuation soup with misread letters (OCR header bleed).
    if misread >= 3 and sum(1 for ch in text if ch in ")-;|/") >= 2:
        return True
    return ocr_text_looks_corrupted(text)
