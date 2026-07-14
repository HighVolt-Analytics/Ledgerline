"""Compute fuzzy-duplicate false-positive rate from audit logs (Layer 7).

Usage:
  python -m scripts.fuzzy_duplicate_fp_report --since 2026-01-01 --until 2026-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time, timezone

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.audit import AuditLog


def _parse_day(value: str, *, end: bool = False) -> datetime:
    d = date.fromisoformat(value)
    t = time(23, 59, 59) if end else time(0, 0, 0)
    return datetime.combine(d, t, tzinfo=timezone.utc)


async def compute_fuzzy_fp_rate(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    async with AsyncSessionLocal() as session:
        stmt = select(AuditLog).where(
            AuditLog.event.in_(
                (
                    "fuzzy_duplicate_suspected",
                    "invoice_approved",
                    "invoice_rejected",
                )
            )
        )
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLog.created_at <= until)
        rows = (await session.execute(stmt.order_by(AuditLog.created_at.asc()))).scalars().all()

    fuzzy_flags = [r for r in rows if r.event == "fuzzy_duplicate_suspected"]
    resolutions_by_invoice: dict[int, str] = {}
    for r in rows:
        if r.event not in {"invoice_approved", "invoice_rejected"}:
            continue
        if r.invoice_id is None:
            continue
        detail = r.detail if isinstance(r.detail, dict) else {}
        resolution = detail.get("resolution")
        if isinstance(resolution, str) and resolution.strip():
            resolutions_by_invoice[r.invoice_id] = resolution.strip()

    not_duplicate = 0
    confirmed = 0
    unresolved = 0
    for flag in fuzzy_flags:
        inv_id = flag.invoice_id
        if inv_id is None:
            unresolved += 1
            continue
        resolution = resolutions_by_invoice.get(inv_id)
        if resolution == "not_duplicate":
            not_duplicate += 1
        elif resolution == "confirmed_duplicate":
            confirmed += 1
        else:
            unresolved += 1

    total = len(fuzzy_flags)
    resolved = not_duplicate + confirmed
    fp_rate = (not_duplicate / resolved) if resolved else None
    return {
        "fuzzy_flags": total,
        "resolved": resolved,
        "not_duplicate": not_duplicate,
        "confirmed_duplicate": confirmed,
        "unresolved": unresolved,
        "false_positive_rate": fp_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuzzy duplicate false-positive report")
    parser.add_argument("--since", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--until", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()
    since = _parse_day(args.since) if args.since else None
    until = _parse_day(args.until, end=True) if args.until else None
    payload = asyncio.run(compute_fuzzy_fp_rate(since=since, until=until))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
