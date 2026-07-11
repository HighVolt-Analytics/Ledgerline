#!/usr/bin/env python3
"""Probe DB state for E2E session scenario testing."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.payment import Payment
from app.models.purchase_order import PurchaseOrder
from app.models.tenant import Tenant
from app.tenant_child_tables import journal_entries_for_invoice


def _ser(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "value"):
        return obj.value
    return obj


async def probe_invoice(session, inv_id: int) -> dict:
    inv = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == inv_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    if not inv:
        return {"id": inv_id, "found": False}

    jc = (
        await session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
        )
    ).scalar()

    journals = (
        await session.execute(
            select(JournalEntry)
            .where(*journal_entries_for_invoice(inv.tenant_id, inv.id))
            .order_by(JournalEntry.id)
        )
    ).scalars().all()

    match_log = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event.in_(
                    [
                        "three_way_match_evaluated",
                        "approval_required",
                        "three_way_match_variance_unapproved",
                        "journal_control_account_unresolved",
                        "invoice_processed",
                    ]
                ),
            )
            .order_by(AuditLog.id.desc())
            .limit(5)
        )
    ).scalars().all()

    return {
        "found": True,
        "id": inv.id,
        "tenant_id": str(inv.tenant_id),
        "invoice_no": inv.invoice_no,
        "vendor": inv.vendor,
        "status": _ser(inv.status),
        "document_type_code": inv.document_type_code,
        "po_reference": inv.po_reference,
        "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
        "subtotal": _ser(inv.subtotal),
        "gst": _ser(inv.gst),
        "total": _ser(inv.total),
        "journal_count": jc,
        "line_items": [
            {
                "description": (li.description or "")[:60],
                "qty": _ser(li.qty),
                "unit_price": _ser(li.unit_price),
                "amount": _ser(li.amount),
            }
            for li in (inv.line_items or [])
        ],
        "journals": [
            {
                "account_code": j.account_code,
                "account_name": j.account_name,
                "debit": _ser(j.debit),
                "credit": _ser(j.credit),
                "entry_type": j.entry_type,
                "entry_kind": getattr(j, "entry_kind", None),
                "vendor_registry_id": getattr(j, "vendor_registry_id", None),
                "customer_registry_id": getattr(j, "customer_registry_id", None),
                "payment_id": getattr(j, "payment_id", None),
            }
            for j in journals
        ],
        "recent_audit": [
            {"event": lg.event, "detail": lg.detail}
            for lg in match_log
        ],
    }


async def find_clean_three_way(session) -> list[dict]:
    rows = (
        await session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.three_way_match_status == "3-Way Match")
            .order_by(PurchaseOrder.id.desc())
            .limit(10)
        )
    ).scalars().all()
    out = []
    for po in rows:
        if po.invoice_id:
            snap = await probe_invoice(session, po.invoice_id)
            snap["po_number"] = po.po_number
            snap["po_id"] = po.id
            snap["variance_approved"] = po.variance_approved
            out.append(snap)
    return out


async def find_thin_coa_tenants(session) -> list[dict]:
    result = await session.execute(
        text(
            """
            SELECT t.id, t.slug, t.name,
                   (rb.config->'chart_of_accounts')::text AS coa_json
            FROM tenants t
            LEFT JOIN rule_book_configs rb ON rb.tenant_id = t.id
            ORDER BY t.created_at DESC
            LIMIT 30
            """
        )
    )
    out = []
    for row in result.mappings():
        coa = row["coa_json"] or "[]"
        has_ar = "receivable" in coa.lower() or "1200" in coa
        has_tax = "tax" in coa.lower() or "2200" in coa
        out.append(
            {
                "tenant_id": str(row["id"]),
                "slug": row["slug"],
                "name": row["name"],
                "coa_account_count": coa.count('"code"'),
                "likely_thin": not (has_ar and has_tax),
            }
        )
    return out


async def payments_for_invoice(session, inv_id: int) -> list[dict]:
    rows = (
        await session.execute(select(Payment).where(Payment.invoice_id == inv_id))
    ).scalars().all()
    return [
        {
            "id": p.id,
            "status": _ser(p.status),
            "amount": _ser(p.amount),
            "vendor": p.vendor,
            "vendor_registry_id": p.vendor_registry_id,
        }
        for p in rows
    ]


async def main() -> None:
    async with async_session_factory() as session:
        print("=== KEY INVOICES ===")
        for iid in [187, 255, 259, 262]:
            print(json.dumps(await probe_invoice(session, iid), indent=2, default=str))

        print("\n=== CLEAN 3-WAY MATCH CANDIDATES ===")
        print(json.dumps(await find_clean_three_way(session), indent=2, default=str))

        print("\n=== TENANT COA SCAN ===")
        print(json.dumps(await find_thin_coa_tenants(session), indent=2))

        print("\n=== PAYMENTS FOR 187 ===")
        print(json.dumps(await payments_for_invoice(session, 187), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
