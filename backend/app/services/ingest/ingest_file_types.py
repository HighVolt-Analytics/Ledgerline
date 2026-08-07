"""Shared accepted document formats for email / upload / file-validity gates.

Keep WhatsApp / Viber / canonical intake / email / upload UI aligned.
"""

from __future__ import annotations

from pathlib import Path

# Documented intake: PDF, JPG/JPEG, PNG, DOCX; WEBP matches WhatsApp/Viber receipts.
ALLOWED_DOCUMENT_SUFFIXES: frozenset[str] = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".webp"}
)

ALLOWED_DOCUMENT_MIME: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)

_MIME_TO_SUFFIX: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/x-pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def normalize_content_type(content_type: str | None) -> str:
    return (content_type or "application/octet-stream").split(";")[0].strip().lower()


def suffix_for_mime(content_type: str | None) -> str | None:
    return _MIME_TO_SUFFIX.get(normalize_content_type(content_type))


def ensure_filename_extension(filename: str | None, content_type: str | None) -> str:
    """Guarantee a basename with an allowed suffix when MIME is known."""
    raw = (filename or "").strip() or "attachment"
    path = Path(raw)
    suffix = path.suffix.lower()
    if suffix in ALLOWED_DOCUMENT_SUFFIXES:
        return path.name
    mime_suffix = suffix_for_mime(content_type)
    if mime_suffix:
        stem = path.stem or "attachment"
        return f"{stem}{mime_suffix}"
    return path.name


def is_allowed_document(
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> bool:
    """True when filename suffix or MIME matches accepted intake formats."""
    name = (filename or "").strip()
    suffix = Path(name).suffix.lower() if name else ""
    if suffix in ALLOWED_DOCUMENT_SUFFIXES:
        return True
    mime = normalize_content_type(content_type)
    if mime in ALLOWED_DOCUMENT_MIME:
        return True
    return False


def accepted_formats_label() -> str:
    return "PDF, JPG, PNG, DOCX, WEBP"
