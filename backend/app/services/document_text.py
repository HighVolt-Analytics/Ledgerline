"""Helpers for persisted OCR body text used in Rule Book classifiers."""

from __future__ import annotations

MAX_DOCUMENT_TEXT_CHARS = 24_000


def sanitize_postgres_text(text: str | None) -> str:
    """Remove NUL bytes — PostgreSQL UTF-8 text columns reject \\x00."""
    if not text:
        return ""
    return text.replace("\x00", "")


def cap_document_text(text: str | None) -> str:
    raw = sanitize_postgres_text(text).strip()
    if len(raw) <= MAX_DOCUMENT_TEXT_CHARS:
        return raw
    return raw[:MAX_DOCUMENT_TEXT_CHARS]
