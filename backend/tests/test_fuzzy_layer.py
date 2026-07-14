"""Layer 4 — fuzzy business duplicate: soft warn, gated, confidence score."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_data import InvoiceData
from app.services.rule_book.validator import all_passed, vr02_unique
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _clear_settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _near_duplicate_seed() -> Invoice:
    return Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Pty Ltd",
        invoice_no="INV-FUZZY-OLD",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        total=Decimal("1000.00"),
        invoice_date=date(2026, 7, 1),
        file_hash="fuzzy-seed-hash",
    )


@pytest.mark.asyncio
async def test_fuzzy_off_by_default_does_not_fail(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUZZY_DUPLICATE_CHECK_ENABLED", "false")
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()

    db_session.add(_near_duplicate_seed())
    await db_session.flush()

    data = InvoiceData(
        vendor="Acme Pty Ltd",
        invoice_no="INV-FUZZY-NEW",
        total=Decimal("1002.00"),
        invoice_date=date(2026, 7, 3),
        currency="AUD",
    )
    result = await vr02_unique(data, db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.passed
    assert "fuzzy" not in result.message


@pytest.mark.asyncio
async def test_fuzzy_on_creates_warn_not_hard_block(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUZZY_DUPLICATE_CHECK_ENABLED", "true")
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()

    db_session.add(_near_duplicate_seed())
    await db_session.flush()

    data = InvoiceData(
        vendor="Acme Pty Ltd",
        invoice_no="INV-FUZZY-NEW",
        total=Decimal("1002.00"),
        invoice_date=date(2026, 7, 3),
        currency="AUD",
    )
    result = await vr02_unique(data, db_session, exclude_id=None, tenant_id=TESTING_TENANT_UUID)
    assert result.passed is False
    assert result.severity == "warn"
    assert "fuzzy" in result.message.lower()
    assert "confidence=" in result.message
    assert all_passed([result]) is True

    audits = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "fuzzy_duplicate_suspected")
        )
    ).scalars().all()
    assert len(audits) >= 1
    detail = audits[-1].detail or {}
    assert "confidence_score" in detail
    assert detail["confidence_score"] is not None


@pytest.mark.asyncio
async def test_fuzzy_tolerances_configurable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUZZY_DUPLICATE_CHECK_ENABLED", "true")
    monkeypatch.setenv("FUZZY_AMOUNT_TOLERANCE_PCT", "0.001")
    monkeypatch.setenv("FUZZY_DATE_WINDOW_DAYS", "2")
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()

    db_session.add(_near_duplicate_seed())
    await db_session.flush()

    # 0.2% amount delta exceeds 0.1% tolerance → no fuzzy hit
    data = InvoiceData(
        vendor="Acme Pty Ltd",
        invoice_no="INV-FUZZY-WIDE",
        total=Decimal("1002.00"),
        invoice_date=date(2026, 7, 3),
        currency="AUD",
    )
    result = await vr02_unique(data, db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.passed
