"""Tests for canonical intake filename normalize, tiers, and page fingerprints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_duplicate_service import (
    classify_match_tier,
    find_existing_ingest_duplicate_match,
    signals_are_sparse,
)
from app.services.ingest.filename_normalize import normalize_attachment_filename
from app.services.ingest.page_fingerprint_service import (
    collect_page_fingerprints,
    page_fingerprint_for_index,
    required_page_fingerprint_matches,
)
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.ingest.canonical_intake_service import (
    canonical_intake_enabled_for,
    validate_intake_file,
    IntakeValidationError,
)


def test_normalize_attachment_filename_strips_noise() -> None:
    assert normalize_attachment_filename("Invoice.PDF") == "invoice.pdf"
    assert normalize_attachment_filename("bundle__part1of3.pdf") == "bundle.pdf"
    assert (
        normalize_attachment_filename("a1b2c3d4-e5f6-7890-abcd-ef1234567890_scan.pdf")
        == "scan.pdf"
    )
    assert normalize_attachment_filename("20240101120000_receipt.PDF") == "receipt.pdf"
    assert normalize_attachment_filename("") == "attachment.bin"
    assert normalize_attachment_filename(None) == "attachment.bin"


def test_filename_only_never_classified_as_hard_tier() -> None:
    # Filename is a booster; classify_match_tier has no filename-only kind that is T1.
    assert classify_match_tier("file_hash") == "T1"
    assert classify_match_tier("business_fingerprint") == "T2"
    assert classify_match_tier("page_fingerprint") == "T3"
    assert classify_match_tier("filename_combo") == "T2"


def test_signals_are_sparse_when_fingerprints_missing() -> None:
    assert signals_are_sparse(
        content_fingerprint=None,
        business_fingerprint=None,
        identity_fields=None,
        page_fingerprints=None,
    )
    assert signals_are_sparse(
        content_fingerprint="abc",
        business_fingerprint=None,
        identity_fields=None,
        page_fingerprints=None,
    )
    assert not signals_are_sparse(
        content_fingerprint="abc",
        business_fingerprint="def",
        identity_fields={"invoice_no": "1"},
        page_fingerprints=None,
    )


def test_page_fingerprint_skips_short_boilerplate() -> None:
    pages = [
        PdfPageText(page_index=0, text="short"),
        PdfPageText(
            page_index=1,
            text="Invoice number INV-1001 vendor Acme Corp total amount one hundred dollars and more text here to pass threshold",
        ),
    ]
    assert page_fingerprint_for_index(pages, 0) is None
    assert page_fingerprint_for_index(pages, 1) is not None
    pairs = collect_page_fingerprints(pages)
    assert len(pairs) == 1
    assert pairs[0][0] == 1


def test_required_page_fingerprint_matches_avoids_single_boilerplate_page() -> None:
    assert required_page_fingerprint_matches(1) == 1
    assert required_page_fingerprint_matches(2) == 2
    assert required_page_fingerprint_matches(3) == 2
    assert required_page_fingerprint_matches(4) == 2
    assert required_page_fingerprint_matches(5) == 3


def test_validate_intake_file() -> None:
    assert validate_intake_file(filename="a.pdf", data=b"%PDF") == "a.pdf"
    with pytest.raises(IntakeValidationError):
        validate_intake_file(filename="a.pdf", data=b"")
    with pytest.raises(IntakeValidationError):
        validate_intake_file(filename="a.exe", data=b"x")


def test_canonical_intake_enabled_for(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CANONICAL_INTAKE_CHANNELS", "upload,email")
    get_settings.cache_clear()
    assert canonical_intake_enabled_for("upload")
    assert canonical_intake_enabled_for("email")
    assert canonical_intake_enabled_for("mailbox")
    assert not canonical_intake_enabled_for("whatsapp")
    get_settings.cache_clear()
    monkeypatch.setenv("CANONICAL_INTAKE_CHANNELS", "")
    get_settings.cache_clear()
    assert not canonical_intake_enabled_for("upload")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_page_fingerprint_lookup_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T3 page lookup must not run unless check_page_fingerprints=True."""
    session = AsyncMock()
    called = {"page": False}

    async def _no_hash(*_a, **_k):
        return None

    async def _page_hit(*_a, **_k):
        called["page"] = True
        inv = MagicMock(spec=Invoice)
        inv.id = 1
        inv.status = InvoiceStatus.PROCESSED
        return inv

    monkeypatch.setattr(
        "app.services.dossier.document_duplicate_service.find_invoice_by_file_hash",
        _no_hash,
    )
    monkeypatch.setattr(
        "app.services.dossier.document_duplicate_service.find_invoice_by_source_file_hash",
        _no_hash,
    )
    monkeypatch.setattr(
        "app.services.ingest.page_fingerprint_service.find_invoice_by_page_fingerprints",
        _page_hit,
    )

    miss = await find_existing_ingest_duplicate_match(
        session,
        tenant_id=uuid.uuid4(),  # type: ignore[arg-type]
        file_hash="abc",
        page_fingerprints=["fp1"],
        check_page_fingerprints=False,
    )
    assert miss is None
    assert called["page"] is False

    hit = await find_existing_ingest_duplicate_match(
        session,
        tenant_id=uuid.uuid4(),  # type: ignore[arg-type]
        file_hash="abc",
        page_fingerprints=["fp1"],
        check_page_fingerprints=True,
    )
    assert hit is not None
    assert hit.match_kind == "page_fingerprint"
    assert hit.confidence_tier == "T3"
    assert called["page"] is True
