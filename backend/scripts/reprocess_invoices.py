#!/usr/bin/env python3
"""Reprocess invoice IDs through the pipeline (local / Azure DB via .env)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.services.approval.approval_service import restore_rejected_invoice_file_if_needed
from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
from app.services.shared.file_storage import (
    ensure_invoice_stored_file,
    repair_invoice_stored_path,
)
from app.workers.tasks import process_invoice_by_id


async def reprocess_one(session, invoice_id: int) -> None:
    inv = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    if inv is None:
        print(f"INV-{invoice_id:03d}: not found")
        return
    label = inv.purchase_document_type or inv.invoice_no or inv.po_reference or "?"
    prev = inv.status.value
    tenant_id = inv.tenant_id
    await repair_invoice_stored_path(session, inv)
    await restore_rejected_invoice_file_if_needed(session, inv)
    await ensure_invoice_stored_file(session, inv)
    await reset_invoice_for_reprocess(session, inv)
    await session.commit()
    if not await process_invoice_by_id(invoice_id, tenant_id=tenant_id):
        print(f"INV-{invoice_id:03d}: pipeline failed")
        return
    inv = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()
    failed: list[dict] = []
    if inv.validation_results:
        try:
            raw = inv.validation_results
            rows = json.loads(raw) if isinstance(raw, str) else raw
            failed = [r for r in rows if not r.get("skipped") and not r.get("passed")]
        except (json.JSONDecodeError, TypeError):
            pass
    print(
        f"INV-{invoice_id:03d} ({label}): {prev} -> {inv.status.value} "
        f"| route={inv.route_target!r} | eval={inv.evaluation_status!r} "
        f"| line_items={len(inv.line_items or [])}"
    )
    if invoice_id == 261:
        li_count = len(inv.line_items or [])
        if li_count < 5:
            print(f"  ACCEPTANCE FAIL: expected >=5 line items, got {li_count}")
        if str(inv.invoice_no or "").strip() != "260371344":
            print(f"  ACCEPTANCE FAIL: invoice_no={inv.invoice_no!r}")
    for row in failed[:6]:
        print(f"  FAIL {row.get('rule')}: {row.get('message')}")


async def main(ids: list[int]) -> None:
    for invoice_id in ids:
        async with async_session_factory() as session:
            await reprocess_one(session, invoice_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", type=int, help="Invoice IDs to reprocess")
    args = parser.parse_args()
    asyncio.run(main(args.ids))
