#!/usr/bin/env python3
"""Manual verification: PO-2026-0612 / invoice 187 variance gate loop."""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.purchase_order import PurchaseOrder
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
from app.services.purchase.purchase_match_service import approve_purchase_variance
from app.tenant_child_tables import journal_entries_for_invoice
from app.workers.tasks import process_invoice_by_id

PO_NUMBER = "PO-2026-0612"
INVOICE_ID = 187
VARIANCE_EVENTS = frozenset(
    {
        "three_way_match_variance_unapproved",
        "purchase_variance_approved",
        "variance_approval_reprocess_queued",
        "variance_approval_posting_resumed",
        "invoice_processed",
        "ocr_completed",
        "parse_completed",
        "mapping_applied",
    }
)


def _money(value) -> str:
    if value is None:
        return "null"
    return str(value)


async def _snapshot(session, invoice_id: int) -> dict:
    inv = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    if inv is None:
        return {"found": False}

    journal_count = (
        await session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()

    po = (
        await session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.tenant_id == inv.tenant_id,
                PurchaseOrder.po_number == PO_NUMBER,
            )
        )
    ).scalar_one_or_none()

    lines = [
        {
            "qty": _money(li.qty),
            "unit_price": _money(li.unit_price),
            "amount": _money(li.amount),
            "description": (li.description or "")[:40],
        }
        for li in (inv.line_items or [])
    ]

    return {
        "found": True,
        "invoice_id": inv.id,
        "tenant_id": str(inv.tenant_id),
        "invoice_no": inv.invoice_no,
        "status": inv.status.value,
        "vendor": inv.vendor,
        "subtotal": _money(inv.subtotal),
        "gst": _money(inv.gst),
        "total": _money(inv.total),
        "po_reference": inv.po_reference,
        "document_type_code": inv.document_type_code,
        "journal_count": journal_count,
        "line_items": lines,
        "po_id": po.id if po else None,
        "po_variance_approved": bool(po.variance_approved) if po else None,
        "po_invoice_id": po.invoice_id if po else None,
    }


async def _audit_timeline(session, invoice_id: int, tenant_id) -> list[dict]:
    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice_id,
                AuditLog.tenant_id == tenant_id,
            )
            .order_by(AuditLog.id.asc())
        )
    ).scalars().all()
    out = []
    for row in rows:
        if row.event not in VARIANCE_EVENTS:
            continue
        detail = row.detail if isinstance(row.detail, dict) else {}
        slim = {k: detail[k] for k in detail if k in {
            "match_status", "qty_variance_value", "anchor_number", "status", "resume",
            "account_name", "po_number",
        }}
        out.append(
            {
                "id": row.id,
                "event": row.event,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "detail": slim or None,
            }
        )
    return out


async def _wait_pipeline(tenant_id, timeout_sec: int = 180) -> bool:
    for _ in range(timeout_sec):
        async with async_session_factory() as session:
            inv = (
                await session.execute(select(Invoice.status).where(Invoice.id == INVOICE_ID))
            ).scalar_one_or_none()
            if inv is None:
                return False
            if inv not in {InvoiceStatus.PENDING, InvoiceStatus.PARSING, InvoiceStatus.MAPPING, InvoiceStatus.JOURNALING, InvoiceStatus.RECONCILING}:
                return True
        await asyncio.sleep(1)
    return False


async def main() -> None:
    print("=" * 72)
    print("VARIANCE GATE VERIFICATION — PO-2026-0612 / invoice 187")
    print("=" * 72)

    async with async_session_factory() as session:
        baseline = await _snapshot(session, INVOICE_ID)
        if not baseline.get("found"):
            print(f"Invoice {INVOICE_ID} not found in database.")
            return
        print("\n--- BASELINE ---")
        print(json.dumps(baseline, indent=2))

        po = (
            await session.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == baseline["tenant_id"],
                    PurchaseOrder.po_number == PO_NUMBER,
                )
            )
        ).scalar_one_or_none()
        if po is None:
            print(f"PO {PO_NUMBER} not found.")
            return

        po.variance_approved = False
        await session.commit()
        print(f"\nSet {PO_NUMBER} variance_approved=false (po_id={po.id})")

    tenant_uuid = uuid.UUID(baseline["tenant_id"])
    print(f"\n--- REQUEUE + REPROCESS invoice {INVOICE_ID} (expect variance block) ---")
    async with async_session_factory() as session:
        inv = (
            await session.execute(
                select(Invoice)
                .where(Invoice.id == INVOICE_ID)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one()
        await requeue_invoice_for_pipeline(session, inv, preserve_extracted_fields=True)
        await session.commit()

    ok = await process_invoice_by_id(INVOICE_ID, tenant_id=tenant_uuid)
    print(f"process_invoice_by_id returned: {ok}")
    if not ok:
        print("Pipeline task failed to start or invoice missing.")
        return

    finished = await _wait_pipeline(tenant_uuid)
    print(f"Pipeline finished polling: {finished}")

    async with async_session_factory() as session:
        after_block = await _snapshot(session, INVOICE_ID)
        print("\n--- AFTER REPROCESS (expect EXCEPTION, journals=0) ---")
        print(json.dumps(after_block, indent=2))

        hold_count = (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.invoice_id == INVOICE_ID,
                    AuditLog.event == "three_way_match_variance_unapproved",
                )
            )
        ).scalar()

        hold_latest = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == INVOICE_ID,
                    AuditLog.event == "three_way_match_variance_unapproved",
                )
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        print(f"\nthree_way_match_variance_unapproved count: {hold_count}")
        if hold_latest and isinstance(hold_latest.detail, dict):
            print(f"Latest hold detail: {json.dumps(hold_latest.detail, indent=2, default=str)}")

        block_ok = (
            after_block["status"] == InvoiceStatus.EXCEPTION.value
            and after_block["journal_count"] == 0
            and hold_count >= 1
        )
        print(f"\nBLOCK CHECK: {'PASS' if block_ok else 'FAIL'}")

        pre_approve = {
            "vendor": after_block["vendor"],
            "subtotal": after_block["subtotal"],
            "gst": after_block["gst"],
            "total": after_block["total"],
            "line_items": after_block["line_items"],
        }
        print("\n--- PRE-APPROVE FIELD SNAPSHOT (resume must preserve these) ---")
        print(json.dumps(pre_approve, indent=2))

        max_audit_id_before = (
            await session.execute(select(func.max(AuditLog.id)).where(AuditLog.invoice_id == INVOICE_ID))
        ).scalar() or 0

    print(f"\n--- APPROVE VARIANCE on PO {po.id} ---")
    async with async_session_factory() as session:
        po_row = (
            await session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id == po.id)
            )
        ).scalar_one()
        tenant_uuid = po_row.tenant_id
        await approve_purchase_variance(session, tenant_uuid, po_row.id)
        await session.commit()

    async with async_session_factory() as session:
        after_approve = await _snapshot(session, INVOICE_ID)
        print("\n--- AFTER APPROVE-VARIANCE (expect PROCESSED, journals>=1) ---")
        print(json.dumps(after_approve, indent=2))

        journals = (
            await session.execute(
                select(JournalEntry)
                .where(*journal_entries_for_invoice(after_approve["tenant_id"], INVOICE_ID))
                .order_by(JournalEntry.id)
            )
        ).scalars().all()
        print("\n--- JOURNAL LINES ---")
        for j in journals:
            print(
                f"  {j.account_code} {j.account_name}: "
                f"dr={j.debit} cr={j.credit} type={j.entry_type}"
            )

        new_events = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id == INVOICE_ID,
                    AuditLog.id > max_audit_id_before,
                    AuditLog.event.in_(
                        [
                            "purchase_variance_approved",
                            "variance_approval_reprocess_queued",
                            "variance_approval_posting_resumed",
                            "three_way_match_variance_unapproved",
                            "ocr_completed",
                            "parse_completed",
                            "mapping_applied",
                            "invoice_processed",
                        ]
                    ),
                )
                .order_by(AuditLog.id.asc())
            )
        ).scalars().all()

        print("\n--- AUDIT EVENTS SINCE APPROVE (ordered) ---")
        for row in new_events:
            detail = row.detail if isinstance(row.detail, dict) else {}
            slim = {k: detail.get(k) for k in detail if k in {
                "match_status", "status", "resume", "anchor_number", "po_number",
            }}
            print(f"  [{row.id}] {row.event} {slim or ''}")

        queued = sum(1 for r in new_events if r.event == "variance_approval_reprocess_queued")
        resumed = sum(1 for r in new_events if r.event == "variance_approval_posting_resumed")
        ocr_after = sum(1 for r in new_events if r.event == "ocr_completed")
        parse_after = sum(1 for r in new_events if r.event == "parse_completed")
        extra_hold = sum(1 for r in new_events if r.event == "three_way_match_variance_unapproved")

        fields_unchanged = (
            after_approve["vendor"] == pre_approve["vendor"]
            and after_approve["subtotal"] == pre_approve["subtotal"]
            and after_approve["total"] == pre_approve["total"]
            and after_approve["line_items"] == pre_approve["line_items"]
        )

        approve_ok = (
            after_approve["status"] == InvoiceStatus.PROCESSED.value
            and after_approve["journal_count"] >= 1
            and queued == 1
            and resumed == 1
            and ocr_after == 0
            and parse_after == 0
            and extra_hold == 0
            and fields_unchanged
        )

        print("\n--- RESUME CHECKS ---")
        print(f"  status=processed: {after_approve['status'] == InvoiceStatus.PROCESSED.value}")
        print(f"  journals>=1: {after_approve['journal_count'] >= 1}")
        print(f"  reprocess_queued exactly once: {queued == 1} (count={queued})")
        print(f"  posting_resumed exactly once: {resumed == 1} (count={resumed})")
        print(f"  no OCR during resume: {ocr_after == 0}")
        print(f"  no parse during resume: {parse_after == 0}")
        print(f"  no second variance hold: {extra_hold == 0}")
        print(f"  fields unchanged: {fields_unchanged}")
        print(f"\nOVERALL: {'PASS' if block_ok and approve_ok else 'FAIL'}")

        timeline = await _audit_timeline(session, INVOICE_ID, after_approve["tenant_id"])
        print("\n--- FULL VARIANCE-RELATED AUDIT TIMELINE ---")
        for row in timeline[-20:]:
            print(f"  [{row['id']}] {row['created_at']} {row['event']} {row.get('detail') or ''}")


if __name__ == "__main__":
    asyncio.run(main())
