"""Management-page audit events (VR-TE, staff guard, team vendor, three-way match)."""

from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.schemas.purchase import ThreeWayMatchResult
from app.services.audit_detail_helpers import (
    compute_three_way_audit_status,
    validation_audit_detail,
    vr_te_results_for_audit,
)
from app.services.invoice_evaluation_service import ROUTE_TEAM, apply_invoice_evaluation
from app.services.purchase_match_service import persist_three_way_match_audit
from app.services.team_expense_approval import apply_team_expense_approval_gate
from app.services.validator import ValidationResult


def test_vr_te_results_include_receipt_present() -> None:
    results = [
        ValidationResult("VR-TE01", True, "Employee matched: Alex"),
        ValidationResult("VR-TE03", True, "Receipt attachment present"),
    ]
    rows = vr_te_results_for_audit(results, has_receipt_file=True)
    te03 = next(row for row in rows if row["check_id"] == "VR-TE03")
    assert te03["name"] == "Receipt"
    assert te03["result"] == "pass"
    assert te03["receipt_present"] is True


def test_validation_audit_detail_team_and_expense_routes() -> None:
    team_results = [ValidationResult("VR-TE01", True, "ok")]
    team_detail = validation_audit_detail(team_results, route_target=ROUTE_TEAM, has_receipt_file=True)
    assert team_detail is not None
    assert "vr_te_results" in team_detail

    expense_results = [ValidationResult("VR01", True, "ok"), ValidationResult("VR03", True, "ok")]
    expense_detail = validation_audit_detail(
        expense_results,
        route_target="Expenses Management",
        has_receipt_file=True,
    )
    assert expense_detail is not None
    assert "vr_results" in expense_detail
    assert expense_detail["route_target"] == "Expenses Management"


def test_compute_three_way_audit_status() -> None:
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-1",
        po_document_id=10,
        invoice_id=20,
    )
    po.goods_receipts = [
        GoodsReceipt(purchase_order_id=1, grn_qty=Decimal("1"), grn_date=None)
    ]
    full = ThreeWayMatchResult(
        status="3-Way Match",
        qty_variance_value=0,
        price_variance_value=0,
        total_deviation=0,
        po_value=100,
        invoice_value=100,
        invoice_gst=10,
        invoice_total=110,
    )
    assert compute_three_way_audit_status(po, full) == "full_match"

    partial = ThreeWayMatchResult(
        status="No GRN",
        qty_variance_value=0,
        price_variance_value=0,
        total_deviation=0,
        po_value=100,
        invoice_value=0,
        invoice_gst=0,
        invoice_total=0,
    )
    po_no_grn = PurchaseOrder(tenant_id=1, po_number="PO-2", po_document_id=10)
    po_no_grn.goods_receipts = []
    assert compute_three_way_audit_status(po_no_grn, partial) == "partial"


@pytest.mark.asyncio
async def test_persist_three_way_match_audit_writes_event(
    db_session: AsyncSession,
) -> None:
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-AUDIT-001",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("100"),
        po_document_id=None,
    )
    db_session.add(po)
    await db_session.flush()

    await persist_three_way_match_audit(db_session, po, None, invoice_id_for_audit=99)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "three_way_match_evaluated")
        )
    ).scalar_one()
    assert row.detail["status"] == "partial"
    assert row.detail["po_present"] is False
    assert po.three_way_match_status == "partial"


@pytest.mark.asyncio
async def test_persist_three_way_match_audit_on_sync_logs_when_unchanged(
    db_session: AsyncSession,
) -> None:
    po = PurchaseOrder(
        tenant_id=1,
        po_number="PO-AUDIT-002",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("100"),
        po_document_id=None,
        three_way_match_status="partial",
    )
    db_session.add(po)
    await db_session.flush()

    await persist_three_way_match_audit(
        db_session,
        po,
        None,
        invoice_id_for_audit=100,
        audit_on_sync=True,
    )
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "three_way_match_evaluated")
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unmatched_team_vendor_audit(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=1,
        route_target=ROUTE_TEAM,
        vendor="Unknown Cafe",
        email_sender="staff@example.com",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="team-vendor-audit-1",
    )
    db_session.add(inv)
    await db_session.flush()
    await db_session.refresh(inv, attribute_names=["line_items"])

    await apply_invoice_evaluation(db_session, inv, enqueue_pending=False)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "unmatched_team_vendor",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.detail["vendor_name"] == "Unknown Cafe"


@pytest.mark.asyncio
async def test_team_expense_auto_approved_audit(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=1,
        route_target=ROUTE_TEAM,
        vendor="Local Cafe",
        total=Decimal("24.50"),
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="team-auto-approve-1",
        email_sender="ops@acme-hospitality.com.au",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Site supervisor lunch",
            qty=Decimal("1"),
            unit_price=Decimal("24.50"),
            amount=Decimal("24.50"),
        )
    )
    await db_session.flush()
    await db_session.refresh(inv, attribute_names=["line_items"])

    held = await apply_team_expense_approval_gate(db_session, inv)
    assert held is False
    await db_session.commit()

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "team_expense_auto_approved",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.detail["amount"] == 24.5
