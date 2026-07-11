"""Read-only probe: heading reconcile audits that may have been wrong."""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from app.database import async_session_factory
from app.models.audit import AuditLog


async def main() -> None:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.event == "classification_heading_reconcile")
                .order_by(AuditLog.id.desc())
                .limit(100)
            )
        ).scalars().all()
        print(f"heading_reconcile_events={len(rows)}")
        override_reasons = {
            "heading_stronger_than_llm_dt",
            "heading_conflicts_with_llm_dt",
        }
        overrides = []
        for r in rows:
            d = r.detail if isinstance(r.detail, dict) else {}
            reason = d.get("reason")
            print(
                f"  inv={r.invoice_id} reason={reason} "
                f"adopted={d.get('adopted_dt')} prev={d.get('previous_dt')} "
                f"kind={d.get('heading_kind')}"
            )
            if reason in override_reasons and d.get("previous_dt"):
                overrides.append((r.invoice_id, d))

        print(f"llm_override_count={len(overrides)}")
        if not overrides:
            print("evidence=no_live_false_overrides_found_or_no_events")
            return

        inv_ids = [i for i, _ in overrides if i]
        # Later human resolve / document_classified with different code
        later = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.invoice_id.in_(inv_ids),
                    AuditLog.event.in_(
                        (
                            "classification_resolved",
                            "human_classification_confirmed",
                            "policy_after_extract_corrected",
                            "routing_review_required",
                        )
                    ),
                )
                .order_by(AuditLog.id.desc())
                .limit(80)
            )
        ).scalars().all()
        print(f"followup_events={len(later)}")
        for r in later:
            d = r.detail if isinstance(r.detail, dict) else {}
            print(f"  follow inv={r.invoice_id} event={r.event} detail={json.dumps(d)[:240]}")


if __name__ == "__main__":
    asyncio.run(main())
