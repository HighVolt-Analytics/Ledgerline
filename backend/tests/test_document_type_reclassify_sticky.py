"""Sticky document type on rule-book remap — existing classifications must not drift."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.classification_decision import PolicyScoreResult
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_reclassify_service import reclassify_invoice_document_type
from app.services.invoice.remap_service import remap_invoices_for_tenant
from app.tenant_ids import TESTING_TENANT_UUID


async def _loaded_invoice(db_session: AsyncSession, invoice_id: int) -> Invoice:
    return (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_reclassify_skips_when_code_still_in_catalogue(
    db_session: AsyncSession,
    capture_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Sysco Foods",
        po_reference="PO-MKT-2026-100",
        document_text="GOODS RECEIPT NOTE",
        document_type_code="DT-03",
        document_type_confidence=0.92,
    )
    db_session.add(inv)
    await db_session.flush()
    inv = await _loaded_invoice(db_session, inv.id)

    def _mock_policy_score(**_kwargs) -> PolicyScoreResult:
        return PolicyScoreResult(winner_dt="DT-02", winner_confidence=0.99, scores=[])

    monkeypatch.setattr(
        "app.services.document_type_reclassify_service.score_all_enabled_dts",
        _mock_policy_score,
    )

    changed = await reclassify_invoice_document_type(db_session, inv, config=capture_config)
    assert changed is False
    assert inv.document_type_code == "DT-03"
    assert float(inv.document_type_confidence or 0) == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_reclassify_force_overrides_sticky_code(
    db_session: AsyncSession,
    capture_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="USD",
        vendor="Directus Cloud",
        invoice_no="INV-9",
        total=Decimal("99.00"),
        document_type_code="DT-24",
        document_type_confidence=0.45,
    )
    db_session.add(inv)
    await db_session.flush()
    inv = await _loaded_invoice(db_session, inv.id)

    def _mock_policy_score(**_kwargs) -> PolicyScoreResult:
        return PolicyScoreResult(winner_dt="DT-21", winner_confidence=0.85, scores=[])

    monkeypatch.setattr(
        "app.services.document_type_reclassify_service.score_all_enabled_dts",
        _mock_policy_score,
    )

    changed = await reclassify_invoice_document_type(
        db_session,
        inv,
        config=capture_config,
        force=True,
    )
    assert changed is True
    assert inv.document_type_code == "DT-21"


@pytest.mark.asyncio
async def test_reclassify_orphan_code_when_dt_removed_from_catalogue(
    db_session: AsyncSession,
    capture_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Vendor Co",
        invoice_no="INV-100",
        total=Decimal("100.00"),
        document_type_code="DT-99",
        document_type_confidence=0.8,
    )
    db_session.add(inv)
    await db_session.flush()
    inv = await _loaded_invoice(db_session, inv.id)

    def _mock_policy_score(**_kwargs) -> PolicyScoreResult:
        return PolicyScoreResult(winner_dt="DT-21", winner_confidence=0.85, scores=[])

    monkeypatch.setattr(
        "app.services.document_type_reclassify_service.score_all_enabled_dts",
        _mock_policy_score,
    )

    changed = await reclassify_invoice_document_type(db_session, inv, config=capture_config)
    assert changed is True
    assert inv.document_type_code == "DT-21"


@pytest.mark.asyncio
async def test_reclassify_skips_human_confirmed_dt(
    db_session: AsyncSession,
    capture_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Vendor Co",
        document_text="CLEARANCE PERMIT",
        document_type_code="DT-02",
        document_type_confidence=0.9,
    )
    db_session.add(inv)
    await db_session.flush()
    await log_event(
        db_session,
        "classification_resolved",
        invoice_id=inv.id,
        detail={"confirmed_dt": "DT-02"},
    )
    await db_session.flush()

    def _mock_policy_score(**_kwargs) -> PolicyScoreResult:
        return PolicyScoreResult(winner_dt="DT-03", winner_confidence=0.99, scores=[])

    monkeypatch.setattr(
        "app.services.document_type_reclassify_service.score_all_enabled_dts",
        _mock_policy_score,
    )

    changed = await reclassify_invoice_document_type(db_session, inv, config=capture_config)
    assert changed is False
    assert inv.document_type_code == "DT-02"


@pytest.mark.asyncio
async def test_remap_preserves_document_type_for_classified_invoice(
    db_session: AsyncSession,
    capture_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        vendor="Sysco Foods",
        po_reference="PO-MKT-2026-100",
        document_text="GOODS RECEIPT NOTE",
        document_type_code="DT-03",
        document_type_confidence=0.91,
        account_code="5000",
        account_name="Inventory",
    )
    db_session.add(inv)
    await db_session.flush()
    inv_id = inv.id

    def _mock_policy_score(**_kwargs) -> PolicyScoreResult:
        return PolicyScoreResult(winner_dt="DT-02", winner_confidence=0.99, scores=[])

    monkeypatch.setattr(
        "app.services.document_type_reclassify_service.score_all_enabled_dts",
        _mock_policy_score,
    )

    result = await remap_invoices_for_tenant(db_session, tenant_id=TESTING_TENANT_UUID)
    loaded = await _loaded_invoice(db_session, inv_id)

    assert loaded.document_type_code == "DT-03"
    assert float(loaded.document_type_confidence or 0) == pytest.approx(0.91)
    assert result.total >= 1
