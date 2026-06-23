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
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.pipeline import process_invoice


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
    await reset_invoice_for_reprocess(session, inv)
    await session.flush()
    await process_invoice(session, inv)
    await session.commit()
    await session.refresh(inv)
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
        f"| route={inv.route_target!r} | eval={inv.evaluation_status!r}"
    )
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
