"""Verify Inbox column fields are consistent (DB vs rule book re-evaluation)."""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.services.purchase.expense_vendor_policy import (
    expense_vendor_hold_above,
    vendor_detection_evaluation_status,
)
from app.services.invoice.invoice_evaluation_service import load_config_for_org
from app.services.rule_book.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_book.rule_engine import detect_vendor
from app.services.master_data.vendor_detection import find_matching_vendor_master


def vr_pass(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        rules = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    evaluated = [r for r in rules if not r.get("skipped")]
    if not evaluated:
        return None
    passed = sum(1 for r in evaluated if r.get("passed"))
    return round(100 * passed / len(evaluated))


async def main(org_id: int = 1) -> int:
    config = load_config_for_org(org_id)
    threshold = config.vendor_detection_config.threshold
    hold = expense_vendor_hold_above(config)
    print(f"org={org_id} threshold={threshold} expense_hold_above={hold}")
    print("-" * 110)

    issues_total = 0
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Invoice)
                .where(Invoice.org_id == org_id)
                .order_by(Invoice.id.desc())
                .limit(20)
            )
        ).scalars().all()

        for inv in rows:
            doc = invoice_to_eval_document(inv)
            vm = detect_vendor(doc, config.vendor_masters, config.vendor_detection_config)
            known = find_matching_vendor_master(doc.vendor, doc.abn, config.vendor_masters)
            amt = float(inv.total) if inv.total is not None else None
            expected_flag = vendor_detection_evaluation_status(
                route_target=inv.route_target,
                confidence=vm.confidence,
                threshold=threshold,
                known_master=known,
                amount=amt,
                hold_above=hold,
            )
            issues: list[str] = []
            stored_conf = inv.vendor_confidence
            if stored_conf is not None and abs(stored_conf - vm.confidence) > 0.01:
                issues.append(
                    f"vendor_confidence drift: stored={stored_conf} recomputed={vm.confidence}"
                )
            es = (inv.evaluation_status or "").strip()
            if es in ("unmatched_expense_vendor", "pending_vendor") and stored_conf is not None:
                if stored_conf >= threshold:
                    issues.append("vendor-flag evaluation but confidence >= threshold")
            if inv.status.value == "processed" and es == "pending_vendor":
                issues.append("processed while still pending_vendor (should be held)")
            route = (inv.route_target or "-")[:20]
            vendor = (inv.vendor or "-")[:28]
            print(
                f"#{inv.id:>2} status={inv.status.value:12} route={route:20} "
                f"eval={es:26} conf={stored_conf!s:>5} vr={vr_pass(inv.validation_results)!s:>4}% "
                f"vendor={vendor}"
            )
            for issue in issues:
                print(f"     ISSUE: {issue}")
                issues_total += 1

    print("-" * 110)
    if issues_total:
        print(f"Found {issues_total} wiring issue(s)")
        return 1
    print("All checked invoices have consistent evaluation/confidence wiring")
    return 0


if __name__ == "__main__":
    org = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    raise SystemExit(asyncio.run(main(org)))
