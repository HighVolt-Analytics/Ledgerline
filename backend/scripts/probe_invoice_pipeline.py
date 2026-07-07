"""Build dossier pipeline for an invoice from live DB."""
import argparse
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.services.dossier.dossier_pipeline_service import build_dossier_pipeline, first_pipeline_failure


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
        logs = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.invoice_id == inv.id)
                .order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
        pipeline = build_dossier_pipeline(inv, logs)
        fail = first_pipeline_failure(pipeline)
        print(
            f"Invoice {inv.id}: status={inv.status} conf={inv.document_type_confidence} "
            f"first_fail={fail.stage_id if fail else None} {fail.exception_code if fail else ''}"
        )
        for step in pipeline:
            if step.state in ("fail", "waived") or step.stage_id in ("validate", "document_type", "bundle", "confidence_gate"):
                checks = ""
                if step.checks:
                    checks = " | " + "; ".join(f"{c.rule_ref}:{c.state}" for c in step.checks[:6])
                print(
                    f"  {step.stage_id}: {step.state} exc={step.exception_code} "
                    f"detail={step.detail!r}{checks}"
                )


if __name__ == "__main__":
    asyncio.run(main())
