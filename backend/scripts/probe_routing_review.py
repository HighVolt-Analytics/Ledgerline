"""Probe routing_review_required audit events."""
import argparse
import asyncio
import json

from sqlalchemy import desc, select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--so-only", action="store_true", help="Only rows with so_reference in optional")
    parser.add_argument("--invoice-id", type=int, default=None)
    parser.add_argument("--scan-validation", action="store_true", help="Find EXCEPTION invoices with so_reference in VR-PB01")
    args = parser.parse_args()

    async with async_session_factory() as s:
        if args.scan_validation:
            rows = (
                await s.execute(
                    select(Invoice)
                    .where(Invoice.status == InvoiceStatus.EXCEPTION)
                    .order_by(desc(Invoice.id))
                    .limit(100)
                )
            ).scalars().all()
            for inv in rows:
                raw = inv.validation_results or ""
                if "so_reference" not in raw:
                    continue
                print(
                    f"id={inv.id} doc={inv.invoice_no!r} dt={inv.document_type_code} "
                    f"conf={inv.document_type_confidence} route={inv.route_target}"
                )
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                for row in parsed:
                    msg = str(row.get("message", ""))
                    if "so_reference" in msg:
                        print(f"  {row.get('rule')}: passed={row.get('passed')} msg={msg}")
            return

        q = (
            select(AuditLog, Invoice)
            .join(Invoice, AuditLog.invoice_id == Invoice.id)
            .where(AuditLog.event == "routing_review_required")
            .order_by(desc(AuditLog.created_at))
            .limit(50)
        )
        if args.invoice_id is not None:
            q = q.where(Invoice.id == args.invoice_id)
        rows = (await s.execute(q)).all()
        for lg, inv in rows:
            d = lg.detail if isinstance(lg.detail, dict) else {}
            pb = d.get("playbook") or {}
            opt = pb.get("missing_optional_extraction_fields") if isinstance(pb, dict) else None
            if args.so_only:
                if not isinstance(opt, list) or "so_reference" not in opt:
                    continue
            print(
                f"id={inv.id} doc={inv.invoice_no!r} dt={inv.document_type_code} "
                f"conf={inv.document_type_confidence} gate={d.get('gate')} at={lg.created_at}"
            )
            if isinstance(pb, dict):
                print(
                    f"  blocks={pb.get('blocks_posting')} tier={pb.get('effective_match_tier')} "
                    f"mand={pb.get('missing_bundle_mandatory')} ext={pb.get('missing_extraction_fields')} "
                    f"opt={opt}"
                )
            print(f"  reasons={d.get('review_reasons')}")


if __name__ == "__main__":
    asyncio.run(main())
