"""Probe adaptive match tiers for existing invoices in the live database.

Run from backend/:
    python scripts/probe_adaptive_match.py
    python scripts/probe_adaptive_match.py --ids 190,191,252,253
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_match_service import resolve_match_mode
from app.services.classification.document_type_playbook_service import evaluate_playbook_gates
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.purchase.purchase_match_service import (
    execute_purchase_document_match,
    resolve_purchase_match_context,
)
from app.services.rule_book.rule_book_mapper import load_classification_config
from app.services.sales.sales_match_service import (
    execute_ar_document_match,
    resolve_ar_match_context,
)


async def main() -> None:
    async with async_session_factory() as session:
        inv_count = (await session.execute(select(func.count()).select_from(Invoice))).scalar_one()
        po_count = (await session.execute(select(func.count()).select_from(PurchaseOrder))).scalar_one()
        so_count = (await session.execute(select(func.count()).select_from(SalesOrder))).scalar_one()
        print(f"=== DB snapshot: {inv_count} invoices, {po_count} POs, {so_count} SOs ===\n")

        for route, label in [(ROUTE_PURCHASE, "PURCHASE"), (ROUTE_SALES, "SALES")]:
            rows = (
                await session.execute(
                    select(Invoice)
                    .where(Invoice.route_target == route)
                    .order_by(Invoice.id.desc())
                    .limit(15)
                    .options(selectinload(Invoice.line_items))
                )
            ).scalars().all()
            print(f"--- {label} (latest {len(rows)}) ---")
            if not rows:
                print("  (none)\n")
                continue
            for inv in rows:
                ref = inv.po_reference or inv.so_reference or inv.invoice_no or "-"
                doc_type = inv.purchase_document_type or inv.sales_document_type or inv.document_type_code or "?"
                if route == ROUTE_PURCHASE:
                    ctx = await resolve_purchase_match_context(session, inv)
                else:
                    ctx = await resolve_ar_match_context(session, inv)
                print(
                    f"  id={inv.id} status={inv.status.value} type={doc_type} "
                    f"ref={ref} tier={ctx.effective_mode}"
                )
            print()

        commercial = (
            await session.execute(
                select(Invoice)
                .where(Invoice.route_target == ROUTE_PURCHASE)
                .order_by(Invoice.id.desc())
                .limit(1)
                .options(selectinload(Invoice.line_items))
            )
        ).scalars().first()
        if commercial:
            config = await load_classification_config(session, commercial.tenant_id)
            definition = get_document_type_definition(
                commercial.document_type_code,
                document_types=config.document_types,
            )
            parsed = InvoiceData(
                vendor=commercial.vendor,
                invoice_no=commercial.invoice_no,
                po_reference=commercial.po_reference,
                total=commercial.total,
            )
            gates = await evaluate_playbook_gates(
                session,
                invoice=commercial,
                parsed=parsed,
                definition=definition,
                document_types=config.document_types,
            )
            detail = gates.audit_detail()
            print("--- Playbook gate (latest purchase invoice) ---")
            print(
                f"  invoice_id={commercial.id} po_ref={commercial.po_reference!r} "
                f"invoice_no={commercial.invoice_no!r}"
            )
            print(
                f"  effective_tier={gates.effective_match_tier} "
                f"completeness={detail.get('dossier_completeness')}"
            )
            print(
                f"  blocks_posting={gates.blocks_posting} "
                f"advisory={list(gates.missing_bundle_advisory)} "
                f"blocking={list(gates.missing_bundle_mandatory)}"
            )


async def probe_ids(invoice_ids: list[int]) -> None:
    async with async_session_factory() as session:
        for iid in invoice_ids:
            inv = (
                await session.execute(
                    select(Invoice)
                    .where(Invoice.id == iid)
                    .options(selectinload(Invoice.line_items))
                )
            ).scalar_one_or_none()
            if inv is None:
                print(f"id={iid} NOT FOUND\n")
                continue
            route = (inv.route_target or "").strip()
            mode = resolve_match_mode(document_type_code=inv.document_type_code)
            if route == ROUTE_SALES:
                ctx = await resolve_ar_match_context(session, inv)
                outcome = await execute_ar_document_match(mode, session=session, invoice=inv)
            else:
                ctx = await resolve_purchase_match_context(session, inv)
                outcome = await execute_purchase_document_match(mode, session=session, invoice=inv)
            po = None
            if (inv.po_reference or "").strip():
                po = (
                    await session.execute(
                        select(PurchaseOrder).where(
                            PurchaseOrder.tenant_id == inv.tenant_id,
                            PurchaseOrder.po_number == inv.po_reference.strip(),
                        )
                    )
                ).scalar_one_or_none()
            config = await load_classification_config(session, inv.tenant_id)
            definition = get_document_type_definition(
                inv.document_type_code,
                document_types=config.document_types,
            )
            gates = await evaluate_playbook_gates(
                session,
                invoice=inv,
                parsed=InvoiceData(
                    vendor=inv.vendor,
                    invoice_no=inv.invoice_no,
                    po_reference=inv.po_reference,
                    total=inv.total,
                ),
                definition=definition,
                document_types=config.document_types,
            )
            print(f"=== Invoice {iid} ===")
            print(
                f"  route={route} status={inv.status.value} "
                f"po_ref={inv.po_reference!r} so_ref={inv.so_reference!r} invoice_no={inv.invoice_no!r}"
            )
            print(f"  doc_type={inv.purchase_document_type or inv.sales_document_type or inv.document_type_code}")
            print(f"  tier={ctx.effective_mode} VR15={outcome.status} passed={outcome.passed}")
            print(
                f"  playbook: completeness={gates.audit_detail().get('dossier_completeness')} "
                f"blocks={gates.blocks_posting} advisory={list(gates.missing_bundle_advisory)}"
            )
            if po:
                grn_n = len(po.goods_receipts) if po.goods_receipts else 0
                print(f"  PO register id={po.id} grn_count={grn_n}")
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="Comma-separated invoice IDs for detailed probe")
    args = parser.parse_args()
    if args.ids:
        asyncio.run(probe_ids([int(x.strip()) for x in args.ids.split(",") if x.strip()]))
    else:
        asyncio.run(main())
