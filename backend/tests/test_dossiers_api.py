
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for dossier API."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_ref_service import assign_document_ref
from app.services.dossier.dossier_pipeline_service import build_dossier_pipeline, first_pipeline_failure
from app.services.dossier.dossier_service import build_dossier_summary, dossier_public_id, resolve_invoice_for_dossier


@pytest.mark.asyncio
async def test_dossier_public_id_fallback(db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="Acme", status=InvoiceStatus.PENDING)
    db_session.add(inv)
    await db_session.flush()
    assert dossier_public_id(inv) == f"DOC-{inv.id}"


@pytest.mark.asyncio
async def test_resolve_invoice_by_doc_id_fallback(db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="X", status=InvoiceStatus.PENDING, file_hash="resolve-doc-fallback")
    db_session.add(inv)
    await db_session.flush()
    token = f"DOC-{inv.id}"
    found = await resolve_invoice_for_dossier(db_session, TESTING_TENANT_UUID, token)
    assert found is not None
    assert found.id == inv.id


@pytest.mark.asyncio
async def test_pipeline_duplicate_fail(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        file_hash="abc",
    )
    db_session.add(inv)
    await db_session.flush()
    await assign_document_ref(db_session, inv)
    logs = [
        AuditLog(
            event="email_ingested",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={"actor_name": "Email"},
        ),
        AuditLog(
            event="duplicate_skipped",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={"reason": "hash match"},
        ),
    ]
    pipeline = build_dossier_pipeline(inv, logs)
    fail = first_pipeline_failure(pipeline)
    assert fail is not None
    assert fail.stage_id == "duplicate"
    blocked = [s for s in pipeline if s.stage_id == "extract"][0]
    assert blocked.blocked_reason and blocked.blocked_reason.startswith("Blocked —")


@pytest.mark.asyncio
async def test_get_dossier_api(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Meridian Foods Pty Ltd",
        invoice_no="INV-9001",
        document_type_code="DT-01",
        document_type_confidence=0.99,
        status=InvoiceStatus.PROCESSED,
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        currency="AUD",
        file_hash="dossier-api-1",
    )
    db_session.add(inv)
    await db_session.flush()
    await assign_document_ref(db_session, inv)
    db_session.add(
        AuditLog(
            event="invoice_uploaded",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={},
        )
    )
    db_session.add(
        AuditLog(
            event="parse_completed",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={"confidence": 99},
        )
    )
    db_session.add(
        AuditLog(
            event="validation_passed",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={},
        )
    )
    db_session.add(
        AuditLog(
            event="invoice_processed",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
            detail={},
        )
    )
    await db_session.flush()

    dossier_id = inv.document_ref
    res = await client.get(f"/api/dossiers/{dossier_id}")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["id"] == dossier_id
    assert body["invoice_id"] == inv.id
    assert body["vendor"] == "Meridian Foods Pty Ltd"
    assert len(body["pipeline"]) == 20
    assert body["linked_documents"]["linkage_kind"] in {"po_reference", "standalone"}
    assert body["approval_chain"]["policy_mode"]


@pytest.mark.asyncio
async def test_list_dossiers_api(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        invoice_no="INV-9002",
        document_type_code="DT-01",
        status=InvoiceStatus.MAPPING,
        file_hash="dossier-api-2",
    )
    db_session.add(inv)
    await db_session.flush()
    await assign_document_ref(db_session, inv)
    await db_session.flush()

    res = await client.get("/api/dossiers?page=1&page_size=12")
    assert res.status_code == 200
    payload = res.json()
    assert payload["meta"]["total"] >= 1
    assert any(row["id"] == inv.document_ref for row in payload["data"])


@pytest.mark.asyncio
async def test_get_sales_dossier_api_fields(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="INV-9001",
        document_type_code="DT-06",
        route_target="Sales Management",
        so_reference="SO-DEMO-100",
        sales_document_type="invoice",
        status=InvoiceStatus.EXCEPTION,
        file_hash="dossier-sales-api",
    )
    db_session.add(inv)
    await db_session.flush()
    await assign_document_ref(db_session, inv)
    await db_session.flush()

    res = await client.get(f"/api/dossiers/{inv.document_ref}")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["counterparty_label"] == "Customer"
    assert body["route_target"] == "Sales Management"
    assert body["so_reference"] == "SO-DEMO-100"
    assert body["linkage_reference"] == "SO-DEMO-100"
    assert body["po_reference"] is None
    assert body["linked_documents"]["linkage_kind"] == "so_reference"


@pytest.mark.asyncio
async def test_resolve_invoice_for_dossier(db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="X", status=InvoiceStatus.PENDING, file_hash="resolve-1")
    db_session.add(inv)
    await db_session.flush()
    await assign_document_ref(db_session, inv)
    found = await resolve_invoice_for_dossier(db_session, TESTING_TENANT_UUID, inv.document_ref or "")
    assert found is not None
    assert found.id == inv.id
