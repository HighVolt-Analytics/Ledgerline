"""Tests for derive_current_stage — inbox pipeline label from audit + status."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.pipeline_stages import derive_current_stage, derive_list_stage
from tests.conftest import TESTING_TENANT_UUID


def _log(event: str, *, invoice_id: int = 1) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        detail={},
    )


@pytest.mark.asyncio
async def test_current_stage_processed_before_post(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="processed-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("invoice_processed", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Processed"
    assert state == "done"


@pytest.mark.asyncio
async def test_current_stage_posted(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="posted-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    processed = _log("invoice_processed", invoice_id=inv.id)
    published = _log("invoice_published_to_ledger", invoice_id=inv.id)
    db_session.add_all([processed, published])
    await db_session.flush()
    published.id = processed.id + 1

    label, state = derive_current_stage(inv, [processed, published])
    assert label == "Posted"
    assert state == "done"


@pytest.mark.asyncio
async def test_current_stage_exception_needs_review_maps_to_blocked_step(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
        currency="AUD",
        file_hash="exception-stage",
        validation_results='[{"rule":"VR01","passed":true,"message":"ok","skipped":false}]',
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("parse_completed", invoice_id=inv.id),
        _log("validation_passed", invoice_id=inv.id),
        _log("mapping_applied", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Approved"
    assert state == "pending"


@pytest.mark.asyncio
async def test_current_stage_duplicate_skipped(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add(inv)
    await db_session.flush()

    label, state = derive_current_stage(
        inv,
        [_log("duplicate_skipped", invoice_id=inv.id)],
    )
    assert label == "Duplicate"
    assert state == "fail"


@pytest.mark.asyncio
async def test_current_stage_rejected(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="rejected-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    label, state = derive_current_stage(
        inv,
        [_log("invoice_rejected", invoice_id=inv.id)],
    )
    assert label == "Rejected"
    assert state == "fail"


@pytest.mark.asyncio
async def test_current_stage_vault_stored_shows_processed_even_if_status_stale(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Spectra",
        status=InvoiceStatus.PENDING,
        route_target="Vault",
        currency="AUD",
        file_hash="vault-stale-status",
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("parse_completed", invoice_id=inv.id),
        _log("vault_stored", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Processed"
    assert state == "done"


@pytest.mark.asyncio
async def test_current_stage_purchase_supporting_processed(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        status=InvoiceStatus.EXCEPTION,
        purchase_document_type="po",
        currency="AUD",
        file_hash="po-support-processed",
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("parse_completed", invoice_id=inv.id),
        _log("purchase_document_processed", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Processed"
    assert state == "done"


def test_list_stage_from_status_without_audit_logs() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PARSING,
        currency="AUD",
        file_hash="list-stage-parsing",
    )
    label, state = derive_list_stage(inv)
    assert label == "Parsed"
    assert state == "pending"

    inv.status = InvoiceStatus.EXCEPTION
    inv.evaluation_status = "awaiting_classification"
    label, state = derive_list_stage(inv)
    assert label == "Parsed"
    assert state == "pending"

    inv.evaluation_status = "needs_review"
    label, state = derive_list_stage(inv)
    assert label == "Validated"
    assert state == "fail"


def test_list_stage_understood_path_vaulted() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vision Co",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="vision_vaulted",
        currency="AUD",
        file_hash="list-stage-vaulted",
        extracted_fields={"vision_bundle_kind": "soft"},
    )
    label, state = derive_list_stage(inv)
    assert label == "Filed"
    assert state == "done"

    inv.evaluation_status = "vision_header_review"
    label, state = derive_list_stage(inv)
    assert label == "Header review"
    assert state == "pending"

    # Legacy soft-bundle still tagged awaiting_classification.
    inv.evaluation_status = "awaiting_classification"
    label, state = derive_list_stage(inv)
    assert label == "Filed"
    assert state == "done"


@pytest.mark.asyncio
async def test_current_stage_match_fail_before_mapped_on_understood_path(
    db_session: AsyncSession,
) -> None:
    """Match holds must not surface as Mapped (MATRIX order puts Mapped first)."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_approval",
        route_target="Sales Management",
        currency="AUD",
        file_hash="match-fail-stage",
        account_name="Suspense Account",
        sales_document_type="invoice",
        extracted_fields={"vision_bundle_kind": "soft"},
    )
    db_session.add(inv)
    await db_session.flush()

    # Vision path — vault_stored is not terminal when Match still blocks posting.
    logs = [
        AuditLog(
            event="vision_understand_passed",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="vault_stored",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 1, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="validation_passed",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 2, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="match_phase_evaluated",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 3, 0, tzinfo=timezone.utc),
            detail={"match_status": "Price Variance", "status": "mismatch"},
        ),
        AuditLog(
            event="approval_requested",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 4, 0, tzinfo=timezone.utc),
            detail={"reason": "match_not_clean"},
        ),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Match"
    assert state == "fail"

    from app.services.invoice.pipeline_stages import build_matrix_cells

    cells = {c["stage"]: c for c in build_matrix_cells(inv, logs)}
    assert cells["Approved"]["state"] == "fail"
    assert "Price Variance" in cells["Approved"]["detail"]


@pytest.mark.asyncio
async def test_current_stage_processed_supporting_ignores_commercial_match_audit(
    db_session: AsyncSession,
) -> None:
    """SO/DN sync audits commercial variance onto the supporting doc id — not a Match hold."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="auto_coded",
        route_target="Sales Management",
        sales_document_type="so",
        currency="AUD",
        file_hash="so-supporting-match-audit",
        extracted_fields={"vision_bundle_kind": "soft"},
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        AuditLog(
            event="vision_understand_passed",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="sales_document_processed",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 1, 0, tzinfo=timezone.utc),
            detail={},
        ),
        AuditLog(
            event="three_way_match_evaluated",
            invoice_id=inv.id,
            created_at=datetime(2026, 6, 1, 12, 2, 0, tzinfo=timezone.utc),
            detail={"match_status": "Qty Variance", "status": "partial"},
        ),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Processed"
    assert state == "done"

    from app.services.invoice.pipeline_stages import build_matrix_cells

    cells = {c["stage"]: c for c in build_matrix_cells(inv, logs)}
    assert cells["Approved"]["state"] == "done"
    assert cells["Approved"]["state"] != "fail"
