"""Full audit trail for an invoice."""
import argparse
import asyncio

from sqlalchemy import desc, select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("invoice_id", type=int)
    args = parser.parse_args()

    async with async_session_factory() as session:
        inv = (
            await session.execute(select(Invoice).where(Invoice.id == args.invoice_id))
        ).scalar_one_or_none()
        if inv is None:
            print("not found")
            return
        print(
            f"Invoice {inv.id}: doc={inv.invoice_no!r} dt={inv.document_type_code} "
            f"conf={inv.document_type_confidence} llm_conf={inv.llm_confidence} "
            f"status={inv.status} eval={inv.evaluation_status}"
        )
        logs = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.invoice_id == inv.id)
                .order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
        for lg in logs:
            detail = lg.detail if isinstance(lg.detail, dict) else {}
            extra = ""
            if lg.event in ("routing_review_required", "classification_gate_passed", "classification_gate_failed"):
                extra = f" gate={detail.get('gate')} reasons={detail.get('review_reasons')}"
            if lg.event == "document_classified":
                extra = f" code={detail.get('document_type_code')} conf={detail.get('document_type_confidence')}"
            if lg.event == "llm_classified":
                extra = f" dt={detail.get('llm_suggested_dt')} conf={detail.get('llm_confidence')}"
            print(f"  {lg.created_at} id={lg.id} {lg.event}{extra}")


if __name__ == "__main__":
    asyncio.run(main())
