"""Tests for file_validity_gate rejection cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.invoice.file_validity_gate import (
    REJECTION_FILE_CORRUPTED,
    REJECTION_FILE_EMPTY,
    REJECTION_FILE_TOO_LARGE,
    REJECTION_UNSUPPORTED_FILE_TYPE,
    evaluate_file_validity,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "file_validity"


def test_empty_file_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    result = evaluate_file_validity(path)
    assert not result.passed
    assert result.rejection_code == REJECTION_FILE_EMPTY


def test_unsupported_suffix_rejected(tmp_path: Path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    result = evaluate_file_validity(path)
    assert not result.passed
    assert result.rejection_code == REJECTION_UNSUPPORTED_FILE_TYPE


def test_corrupt_pdf_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-not-a-real-pdf")
    result = evaluate_file_validity(path)
    assert not result.passed
    assert result.rejection_code == REJECTION_FILE_CORRUPTED


def test_valid_png_passes(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    path = tmp_path / "scan.png"
    Image.new("RGB", (10, 10), color="white").save(path)
    result = evaluate_file_validity(path)
    assert result.passed


def test_file_too_large_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MAX_UPLOAD_FILE_BYTES", "1024")
    path = tmp_path / "big.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)
    result = evaluate_file_validity(path)
    get_settings.cache_clear()
    assert not result.passed
    assert result.rejection_code == REJECTION_FILE_TOO_LARGE
