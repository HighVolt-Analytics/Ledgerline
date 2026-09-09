"""Phases E–H — purchases, payments, expenses nav, privilege enforcement."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.journal import EntryType, JournalEntry
from app.models.line_item import LineItem
from app.models.payment import Payment, PaymentStatus
from app.models.purchase_order import PurchaseOrder
from app.models.user import User, UserRole
from app.services.auth.auth_service import create_access_token, hash_password
from app.services.auth.membership_service import ensure_membership
from app.tenant_ids import TESTING_TENANT_UUID
from app.services.invoice.invoice_evaluation_service import ROUTE_EXPENSES, ROUTE_PURCHASE
from app.services.payments.payment_service import ensure_payment_for_invoice
from app.schemas.purchase import GoodsReceiptCreate
from app.services.purchase.purchase_match_service import (
    record_goods_receipt,
    sync_purchase_order_from_invoice,
)


@pytest.mark.asyncio
async def test_sync_purchase_order_from_routed_invoice(
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-9001",
        invoice_no="PO-9001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.VALIDATING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Widgets",
            qty=Decimal("10"),
            unit_price=Decimal("50.00"),
            amount=Decimal("500.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, po_doc)
    assert po is not None
    assert po.po_number == "PO-9001"
    assert po.po_document_id == po_doc.id

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-9001",
        invoice_no="INV-9001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.VALIDATING,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal("10"),
            unit_price=Decimal("50.00"),
            amount=Decimal("500.00"),
        )
    )
    await db_session.flush()

    linked = await sync_purchase_order_from_invoice(db_session, inv)
    assert linked is not None
    assert linked.invoice_id == inv.id


@pytest.mark.asyncio
async def test_purchases_api_lists_three_way_match(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-API-1",
        invoice_no="PO-API-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("200.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    await sync_purchase_order_from_invoice(db_session, po_doc)

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-API-1",
        invoice_no="INV-PO-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        evaluation_status="auto_coded",
        matched_rule_ids='["purchase:pr-1"]',
        subtotal=Decimal("200.00"),
        gst=Decimal("20.00"),
        total=Decimal("220.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    await sync_purchase_order_from_invoice(db_session, inv)
    await db_session.commit()

    res = await client.get("/api/purchases")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["po_number"] == "PO-API-1"
    assert rows[0]["match"]["status"] == "No GRN"
    assert rows[0]["route_target"] == ROUTE_PURCHASE
    assert rows[0]["matched_rule_ids"] == ["purchase:pr-1"]
    assert rows[0]["matched_rule_name"] == "Cloud & Hosting POs"
    assert rows[0]["matched_gl"] == "Cloud Hosting Expense"


@pytest.mark.asyncio
async def test_purchases_api_lists_each_invoice_on_shared_po(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Two purchase invoices on the same PO number each get a register row."""
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Shared Vendor",
        po_reference="PO-SHARED-1",
        invoice_no="PO-SHARED-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("1500.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Campaign",
            qty=Decimal("3"),
            unit_price=Decimal("500.00"),
            amount=Decimal("1500.00"),
        )
    )
    await db_session.flush()
    await sync_purchase_order_from_invoice(db_session, po_doc)

    inv_google = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Google Australia Pty Ltd",
        po_reference="PO-SHARED-1",
        invoice_no="GOOG-INV-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("1000.00"),
        gst=Decimal("100.00"),
        total=Decimal("1100.00"),
        status=InvoiceStatus.PROCESSED,
    )
    inv_meta = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Meta Platforms Ireland",
        po_reference="PO-SHARED-1",
        invoice_no="META-INV-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv_google)
    db_session.add(inv_meta)
    await db_session.flush()
    for inv, qty, price in (
        (inv_google, Decimal("2"), Decimal("500.00")),
        (inv_meta, Decimal("1"), Decimal("500.00")),
    ):
        db_session.add(
            LineItem(
                invoice_id=inv.id,
                description="Campaign",
                qty=qty,
                unit_price=price,
                amount=qty * price,
            )
        )
    await db_session.flush()
    await sync_purchase_order_from_invoice(db_session, inv_google)
    await sync_purchase_order_from_invoice(db_session, inv_meta)
    await db_session.commit()

    res = await client.get("/api/purchases")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) == 2
    invoice_nos = {row["invoice_no"] for row in rows}
    assert invoice_nos == {"GOOG-INV-1", "META-INV-1"}
    assert all(row["po_number"] == "PO-SHARED-1" for row in rows)
    vendors = {row["vendor"] for row in rows}
    assert len(vendors) == 1


@pytest.mark.asyncio
async def test_purchases_api_records_grn(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-GRN-1",
        invoice_no="PO-GRN-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("200.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, po_doc)
    assert po is not None

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        po_reference="PO-GRN-1",
        invoice_no="INV-GRN-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("200.00"),
        gst=Decimal("20.00"),
        total=Decimal("220.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Paper",
            qty=Decimal("4"),
            unit_price=Decimal("50.00"),
            amount=Decimal("200.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, inv)
    assert po is not None
    await db_session.commit()

    res = await client.post(
        f"/api/purchases/{po.id}/grn",
        json={"grn_qty": 4, "receiver": "Warehouse A", "condition_note": "Good"},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["grn_qty"] == 4.0
    assert body["match"]["status"] == "3-Way Match"

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "goods_receipt_recorded")
        )
    ).scalars().first()
    assert audit is not None
    assert audit.invoice_id == inv.id


@pytest.mark.asyncio
async def test_purchases_api_approves_variance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="PFD Foods",
        po_reference="PO-VAR-1",
        invoice_no="PO-VAR-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("400.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=po_doc.id,
            description="Stock",
            qty=Decimal("10"),
            unit_price=Decimal("40.00"),
            amount=Decimal("400.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, po_doc)
    assert po is not None

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="PFD Foods",
        po_reference="PO-VAR-1",
        invoice_no="INV-VAR-1",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("480.00"),
        gst=Decimal("48.00"),
        total=Decimal("528.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            invoice_id=inv.id,
            description="Stock",
            qty=Decimal("12"),
            unit_price=Decimal("40.00"),
            amount=Decimal("480.00"),
        )
    )
    await db_session.flush()
    po = await sync_purchase_order_from_invoice(db_session, inv)
    assert po is not None
    await record_goods_receipt(
        db_session,
        TESTING_TENANT_UUID,
        po.id,
        GoodsReceiptCreate(grn_qty=Decimal("10"), receiver="Site B"),
    )
    await db_session.flush()
    await db_session.commit()

    list_res = await client.get("/api/purchases")
    row = next(r for r in list_res.json()["data"] if r["po_number"] == "PO-VAR-1")
    assert row["match"]["status"] in ("Qty Variance", "Routed for Approval")

    approve_res = await client.post(f"/api/purchases/{row['id']}/approve-variance")
    assert approve_res.status_code == 200
    approved = approve_res.json()["data"]
    assert approved["variance_approved"] is True
    assert approved["match"]["status"] == "3-Way Match"

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "purchase_variance_approved")
        )
    ).scalars().first()
    assert audit is not None
    assert audit.invoice_id == inv.id


@pytest.mark.asyncio
async def test_payment_created_for_processed_invoice(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor Pay",
        total=Decimal("1200.00"),
        due_date=__import__("datetime").date(2026, 7, 1),
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase Management",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = await ensure_payment_for_invoice(db_session, inv)
    assert payment is not None
    assert payment.amount == Decimal("1200.00")
    assert payment.status.value == "queue"


@pytest.mark.asyncio
async def test_payments_api_lists_queue(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor Pay",
        total=Decimal("800.00"),
        due_date=__import__("datetime").date(2026, 7, 1),
        status=InvoiceStatus.PROCESSED,
        route_target="Purchase Management",
    )
    db_session.add(inv)
    await db_session.flush()
    await ensure_payment_for_invoice(db_session, inv)
    await db_session.commit()

    res = await client.get("/api/payments")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "queue"


@pytest.mark.asyncio
async def test_nav_badges_include_business_expenses(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Telstra",
            route_target=ROUTE_EXPENSES,
            status=InvoiceStatus.PENDING,
        )
    )
    await db_session.commit()

    res = await client.get("/api/dashboard/badges")
    assert res.status_code == 200
    assert res.json()["data"]["business_expenses_count"] == 1


@pytest.mark.asyncio
async def test_approval_policy_put_writes_audit(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    from app.config import get_settings

    get_settings.cache_clear()

    body = (await client.get("/api/approval-policy")).json()["data"]
    body["matrix"]["Manager"]["Comment"] = False
    res = await client.put("/api/approval-policy", json=body)
    assert res.status_code == 200

    row = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.event == "approval_policy_updated")
            .order_by(AuditLog.id.desc())
        )
    ).scalars().first()
    assert row is not None
    assert row.detail is not None
    assert "before" in row.detail
    assert "after" in row.detail


@pytest.mark.asyncio
async def test_member_cannot_publish_without_privilege(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    admin = User(
        tenant_id=TESTING_TENANT_UUID,
        email="admin@example.com",
        full_name="Admin User",
        password_hash=hash_password("secret"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()
    await ensure_membership(db_session, user_id=admin.id, tenant_id=TESTING_TENANT_UUID, role="admin")
    admin_token = create_access_token(
        user_id=admin.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=admin.email,
        role=UserRole.ADMIN.value,
    )
    policy = (
        await client.get(
            "/api/approval-policy",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()["data"]
    policy["matrix"]["Manager"]["Approve"] = False
    await client.put(
        "/api/approval-policy",
        json=policy,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    user = User(
        tenant_id=TESTING_TENANT_UUID,
        email="member@example.com",
        full_name="Member User",
        password_hash=hash_password("secret"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    await ensure_membership(
        db_session,
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        role="manager",
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="X",
        status=InvoiceStatus.PROCESSED,
        total=Decimal("100"),
    )
    db_session.add(inv)
    await db_session.commit()

    token = create_access_token(
        user_id=user.id,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="testing",
        email=user.email,
        role="manager",
    )
    res = await client.post(
        f"/api/invoices/{inv.id}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_wallet_summary_from_payments(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        total=Decimal("120.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        Payment(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            vendor="Acme",
            amount=Decimal("120.00"),
            status=PaymentStatus.PAID,
        )
    )
    db_session.add(
        Payment(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            vendor="Beta",
            amount=Decimal("80.00"),
            status=PaymentStatus.QUEUE,
        )
    )
    await db_session.commit()

    res = await client.get("/api/payments/wallet-summary")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["balance"] == 200.0
    assert body["available"] == 80.0
    assert len(body["transactions"]) >= 2


@pytest.mark.asyncio
async def test_billing_top_up_adds_credits(
    client: AsyncClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))

    res = await client.get("/api/billing")
    assert res.status_code == 200
    before = res.json()["data"]["balance"]

    buy = await client.post("/api/billing/top-up", json={"amount": "10"})
    assert buy.status_code == 200
    assert buy.json()["data"]["balance"] > before
    assert buy.json()["data"]["plan"] in {"free", "studio", "enterprise"}


@pytest.mark.asyncio
async def test_ledger_link_exports_processed_invoices(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="LL-001",
        invoice_date=date(2026, 5, 1),
        total=Decimal("110.00"),
        status=InvoiceStatus.PROCESSED,
        route_target=ROUTE_EXPENSES,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 5, 1),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("110.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 5, 1),
            account_code="2000",
            account_name="Accounts Payable",
            debit=Decimal("0"),
            credit=Decimal("110.00"),
            entry_type=EntryType.CREDIT,
        )
    )
    await db_session.commit()

    res = await client.get("/api/ledger-link")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["overview"]["balanced"] is True
    assert any(row["doc"] == "LL-001" for row in data["exports"]["bills"])


@pytest.mark.asyncio
async def test_matrix_duplicate_conflict_detail(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    original = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Dup Co",
        invoice_no="DUP-100",
        document_ref="DOC-1",
        file_hash="hash-original",
        total=Decimal("500.00"),
        status=InvoiceStatus.PROCESSED,
    )
    duplicate = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Dup Co",
        invoice_no="DUP-100",
        file_hash="hash-duplicate",
        total=Decimal("520.00"),
        status=InvoiceStatus.DUPLICATE_SKIPPED,
    )
    db_session.add_all([original, duplicate])
    await db_session.commit()

    res = await client.get("/api/matrix")
    assert res.status_code == 200
    rows = res.json()["data"]
    dup_row = next(r for r in rows if r["invoice"]["status"] == "duplicate_skipped")
    assert dup_row["conflict_with"] in {"DUP-100", "DOC-1", f"DOC-{original.id}"}
    assert dup_row["conflict_detail"]
    assert dup_row["conflict_detail"][0]["field"] == "Vendor"
