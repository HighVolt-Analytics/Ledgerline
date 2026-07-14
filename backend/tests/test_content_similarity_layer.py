"""Layer 5 — content similarity boosts fuzzy confidence (not standalone blocking)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.extraction.pdf_content_fingerprint import (
    boost_confidence_with_content_similarity,
    jaccard_token_similarity,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.validator import vr02_unique
from app.tenant_ids import TESTING_TENANT_UUID

_BASE_TEXT = (
    "TAX INVOICE Acme Pty Ltd Invoice for consulting services "
    "line item widgets qty 10 amount 1000 gst included thanks"
)


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_jaccard_high_for_ocr_noise_variants() -> None:
    a = _BASE_TEXT + " invoice no INV1001"
    b = _BASE_TEXT + " invoice no INV100l"  # OCR: 1 vs l
    sim = jaccard_token_similarity(a, b)
    assert sim >= 0.9


def test_boost_only_when_flag_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_SIMILARITY_CHECK_ENABLED", "false")
    get_settings.cache_clear()
    conf, sim = boost_confidence_with_content_similarity(0.7, _BASE_TEXT, _BASE_TEXT)
    assert conf == 0.7
    assert sim is None

    monkeypatch.setenv("CONTENT_SIMILARITY_CHECK_ENABLED", "true")
    monkeypatch.setenv("CONTENT_SIMILARITY_THRESHOLD", "0.90")
    get_settings.cache_clear()
    conf2, sim2 = boost_confidence_with_content_similarity(0.7, _BASE_TEXT, _BASE_TEXT)
    assert sim2 is not None and sim2 >= 0.9
    assert conf2 > 0.7


@pytest.mark.asyncio
async def test_fuzzy_plus_content_similarity_raises_confidence(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUZZY_DUPLICATE_CHECK_ENABLED", "true")
    monkeypatch.setenv("CONTENT_SIMILARITY_CHECK_ENABLED", "true")
    monkeypatch.setenv("CONTENT_SIMILARITY_THRESHOLD", "0.90")
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()

    similar_text = _BASE_TEXT + " invoice no AA1001"
    noisy_text = _BASE_TEXT + " invoice no AA100l"  # OCR noise

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Acme Pty Ltd",
            invoice_no="AA1001",
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            total=Decimal("1000.00"),
            invoice_date=date(2026, 7, 1),
            file_hash="content-sim-seed",
            document_text=similar_text,
        )
    )
    await db_session.flush()

    data = InvoiceData(
        vendor="Acme Pty Ltd",
        invoice_no="BB2002",
        total=Decimal("1001.00"),
        invoice_date=date(2026, 7, 2),
        currency="AUD",
        document_text=noisy_text,
    )
    result = await vr02_unique(data, db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.passed is False
    assert result.severity == "warn"

    # Compare to fuzzy-only confidence without content boost
    monkeypatch.setenv("CONTENT_SIMILARITY_CHECK_ENABLED", "false")
    get_settings.cache_clear()
    result_plain = await vr02_unique(data, db_session, tenant_id=TESTING_TENANT_UUID)

    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "fuzzy_duplicate_suspected")
        )
    ).scalars().all()
    assert len(audits) >= 2
    with_boost = next(a for a in reversed(audits) if (a.detail or {}).get("content_similarity") is not None)
    without = next(a for a in reversed(audits) if (a.detail or {}).get("content_similarity") is None)
    assert with_boost.detail["confidence_score"] > without.detail["confidence_score"]
    assert "confidence=" in result.message
    assert result_plain.severity == "warn"
