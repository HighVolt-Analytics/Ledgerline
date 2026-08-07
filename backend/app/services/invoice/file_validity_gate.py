"""Cheap pre-OCR file validity checks — fail fast before DI/LLM spend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".webp"}
)
ALLOWED_MIME: frozenset[str] = frozenset(
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

REJECTION_UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
REJECTION_FILE_ENCRYPTED = "file_encrypted"
REJECTION_FILE_CORRUPTED = "file_corrupted"
REJECTION_FILE_TOO_LARGE = "file_too_large"
REJECTION_FILE_EMPTY = "file_empty"


@dataclass(frozen=True)
class FileValidityResult:
    passed: bool
    rejection_code: str | None = None
    detail: str | None = None
    file_size_bytes: int = 0
    page_count: int | None = None


def _suffix_allowed(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_SUFFIXES


def _pdf_encrypted(path: Path) -> bool:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            return bool(doc.is_encrypted)
        finally:
            doc.close()
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return bool(reader.is_encrypted)
    except Exception:
        return False


def _pdf_page_count(path: Path) -> int | None:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        return None


def _pdf_readable(path: Path) -> bool:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            if doc.page_count < 1:
                return False
            _ = doc.load_page(0).get_text("text")
            return True
        finally:
            doc.close()
    except Exception:
        return False


def _image_readable(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def evaluate_file_validity(path: str | Path) -> FileValidityResult:
    """Validate stored attachment before OCR/DI."""
    file_path = Path(path)
    if not file_path.is_file():
        return FileValidityResult(
            passed=False,
            rejection_code=REJECTION_FILE_CORRUPTED,
            detail="file_not_found",
        )

    size = file_path.stat().st_size
    if size == 0:
        return FileValidityResult(
            passed=False,
            rejection_code=REJECTION_FILE_EMPTY,
            detail="zero_byte_file",
            file_size_bytes=0,
        )

    if not _suffix_allowed(file_path):
        return FileValidityResult(
            passed=False,
            rejection_code=REJECTION_UNSUPPORTED_FILE_TYPE,
            detail=f"unsupported_suffix:{file_path.suffix.lower() or 'none'}",
            file_size_bytes=size,
        )

    settings = get_settings()
    max_bytes = int(settings.max_upload_file_bytes)
    if size > max_bytes:
        return FileValidityResult(
            passed=False,
            rejection_code=REJECTION_FILE_TOO_LARGE,
            detail=f"size_bytes:{size}",
            file_size_bytes=size,
        )

    suffix = file_path.suffix.lower()
    page_count: int | None = None

    if suffix == ".pdf":
        if not _pdf_readable(file_path):
            if _pdf_encrypted(file_path):
                return FileValidityResult(
                    passed=False,
                    rejection_code=REJECTION_FILE_ENCRYPTED,
                    detail="pdf_password_protected",
                    file_size_bytes=size,
                )
            return FileValidityResult(
                passed=False,
                rejection_code=REJECTION_FILE_CORRUPTED,
                detail="pdf_unreadable",
                file_size_bytes=size,
            )
        page_count = _pdf_page_count(file_path)
        if page_count is not None and page_count > int(settings.max_upload_pdf_pages):
            return FileValidityResult(
                passed=False,
                rejection_code=REJECTION_FILE_TOO_LARGE,
                detail=f"page_count:{page_count}",
                file_size_bytes=size,
                page_count=page_count,
            )
    elif suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        if not _image_readable(file_path):
            return FileValidityResult(
                passed=False,
                rejection_code=REJECTION_FILE_CORRUPTED,
                detail="image_unreadable",
                file_size_bytes=size,
            )
    elif suffix == ".docx":
        try:
            from docx import Document

            Document(file_path)
        except Exception:
            return FileValidityResult(
                passed=False,
                rejection_code=REJECTION_FILE_CORRUPTED,
                detail="docx_unreadable",
                file_size_bytes=size,
            )

    return FileValidityResult(
        passed=True,
        file_size_bytes=size,
        page_count=page_count,
    )


def file_validity_audit_detail(result: FileValidityResult) -> dict[str, object]:
    return {
        "passed": result.passed,
        "rejection_code": result.rejection_code,
        "detail": result.detail,
        "file_size_bytes": result.file_size_bytes,
        "page_count": result.page_count,
        "allowed_suffixes": sorted(ALLOWED_SUFFIXES),
    }
