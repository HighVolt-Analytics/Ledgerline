"""Normalize attachment filenames for soft duplicate confidence boosting."""

from __future__ import annotations

import re
from pathlib import Path

_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[_-]?",
)
_TIMESTAMP_PREFIX_RE = re.compile(r"^\d{8,14}[_-]?")
_PART_SUFFIX_RE = re.compile(r"(?i)__part\d+of\d+$")
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w.\-]+", re.UNICODE)


def normalize_attachment_filename(name: str | None) -> str:
    """
    Lowercase basename suitable as a soft duplicate signal.

    Never use alone as a hard duplicate trigger — common names like invoice.pdf collide.
    """
    raw = (name or "").strip()
    if not raw:
        return "attachment.bin"

    base = Path(raw.replace("\\", "/")).name.strip() or "attachment.bin"
    stem = Path(base).stem
    suffix = Path(base).suffix.lower()

    stem = _PART_SUFFIX_RE.sub("", stem)
    stem = _UUID_RE.sub("", stem)
    stem = _TIMESTAMP_PREFIX_RE.sub("", stem)
    stem = stem.lower().strip(" ._-\t")
    stem = _PUNCT_RE.sub("_", stem)
    stem = _WHITESPACE_RE.sub("_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_")
    if not stem:
        stem = "attachment"

    return f"{stem}{suffix}" if suffix else stem
