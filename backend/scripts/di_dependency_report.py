#!/usr/bin/env python3
"""DI dependency report for Foundry-primary tenants (measurement only).

Answers: if DI enrich were removed under Foundry, how often would posting-critical
fields change (DI chosen vs LLM agreed/disagreed)?

Usage:
  python -m scripts.di_dependency_report
  python -m scripts.di_dependency_report --days 30 --provider azure_foundry_vision
  python -m scripts.di_dependency_report --since 2026-06-01 --until 2026-07-01 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database import async_session_factory

POSTING_FIELDS = ("total", "subtotal", "gst", "line_items", "invoice_no", "vendor")


def _parse_day(value: str, *, end: bool = False) -> datetime:
    d = date.fromisoformat(value)
    t = time(23, 59, 59, 999999) if end else time(0, 0, 0)
    return datetime.combine(d, t, tzinfo=timezone.utc)


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0].keys())
    widths = {col: max(len(col), *(len(str(row.get(col, ""))) for row in rows)) for col in columns}
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    print(header)
    print("-+-".join("-" * widths[col] for col in columns))
    for row in rows:
        print(" | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns))


FIELD_STATS_SQL = """
WITH telemetry AS (
    SELECT
        al.id AS audit_id,
        al.tenant_id,
        al.invoice_id,
        al.created_at,
        al.detail,
        al.detail ->> 'document_ai_provider' AS document_ai_provider,
        COALESCE((al.detail -> 'di_availability' ->> 'di_available')::boolean, false) AS di_available
    FROM audit_logs al
    WHERE al.event = 'field_resolution_telemetry'
      AND al.invoice_id IS NOT NULL
      AND al.created_at >= :since
      AND al.created_at < :until
      AND COALESCE(al.detail ->> 'document_ai_provider', '') = :provider
      AND COALESCE((al.detail ->> 'policy_reextract')::boolean, false) = false
),
latest_per_invoice AS (
    SELECT DISTINCT ON (invoice_id)
        *
    FROM telemetry
    ORDER BY invoice_id, created_at DESC
),
field_rows AS (
    SELECT
        l.tenant_id,
        l.invoice_id,
        l.di_available,
        f.key AS field_name,
        f.value ->> 'chosen_source' AS chosen_source,
        COALESCE((f.value ->> 'agreed')::boolean, false) AS agreed,
        f.value ->> 'di_value' AS di_value,
        f.value ->> 'llm_value' AS llm_value
    FROM latest_per_invoice l
    CROSS JOIN LATERAL jsonb_each(l.detail -> 'fields') AS f(key, value)
    WHERE f.key = ANY(:fields)
)
SELECT
    field_name,
    COUNT(*) AS invoice_count,
    COUNT(*) FILTER (WHERE di_value IS NOT NULL AND di_value <> 'null') AS di_had_value,
    COUNT(*) FILTER (WHERE llm_value IS NOT NULL AND llm_value <> 'null') AS llm_had_value,
    COUNT(*) FILTER (WHERE chosen_source = 'azure_di') AS di_chosen,
    COUNT(*) FILTER (WHERE chosen_source = 'llm') AS llm_chosen,
    COUNT(*) FILTER (WHERE chosen_source = 'fallback') AS fallback_chosen,
    COUNT(*) FILTER (WHERE agreed) AS agreed_count,
    COUNT(*) FILTER (
        WHERE NOT agreed
          AND di_value IS NOT NULL
          AND di_value <> 'null'
          AND llm_value IS NOT NULL
          AND llm_value <> 'null'
    ) AS disagreed_both_present
FROM field_rows
GROUP BY field_name
ORDER BY field_name
"""

DI_AVAILABILITY_SQL = """
WITH telemetry AS (
    SELECT
        al.invoice_id,
        al.created_at,
        COALESCE((al.detail -> 'di_availability' ->> 'di_available')::boolean, false) AS di_available
    FROM audit_logs al
    WHERE al.event = 'field_resolution_telemetry'
      AND al.invoice_id IS NOT NULL
      AND al.created_at >= :since
      AND al.created_at < :until
      AND COALESCE(al.detail ->> 'document_ai_provider', '') = :provider
      AND COALESCE((al.detail ->> 'policy_reextract')::boolean, false) = false
),
latest_per_invoice AS (
    SELECT DISTINCT ON (invoice_id)
        invoice_id,
        di_available
    FROM telemetry
    ORDER BY invoice_id, created_at DESC
)
SELECT
    COUNT(*) AS invoice_count,
    COUNT(*) FILTER (WHERE di_available) AS di_available_count
FROM latest_per_invoice
"""

TENANT_BREAKDOWN_SQL = """
WITH telemetry AS (
    SELECT
        al.tenant_id,
        al.invoice_id,
        al.created_at,
        al.detail
    FROM audit_logs al
    WHERE al.event = 'field_resolution_telemetry'
      AND al.invoice_id IS NOT NULL
      AND al.created_at >= :since
      AND al.created_at < :until
      AND COALESCE(al.detail ->> 'document_ai_provider', '') = :provider
      AND COALESCE((al.detail ->> 'policy_reextract')::boolean, false) = false
),
latest_per_invoice AS (
    SELECT DISTINCT ON (invoice_id)
        tenant_id,
        invoice_id,
        detail
    FROM telemetry
    ORDER BY invoice_id, created_at DESC
),
total_field AS (
    SELECT
        l.tenant_id,
        f.value ->> 'chosen_source' AS chosen_source,
        COALESCE((f.value ->> 'agreed')::boolean, false) AS agreed
    FROM latest_per_invoice l
    CROSS JOIN LATERAL jsonb_each(l.detail -> 'fields') AS f(key, value)
    WHERE f.key = 'total'
)
SELECT
    tenant_id::text AS tenant_id,
    COUNT(*) AS invoices,
    COUNT(*) FILTER (WHERE chosen_source = 'azure_di') AS total_di_chosen,
    COUNT(*) FILTER (WHERE agreed) AS total_agreed
FROM total_field
GROUP BY tenant_id
ORDER BY invoices DESC
"""


async def run_report(
    *,
    since: datetime,
    until: datetime,
    provider: str,
) -> dict[str, Any]:
    params = {
        "since": since,
        "until": until,
        "provider": provider,
        "fields": list(POSTING_FIELDS),
    }
    async with async_session_factory() as session:
        field_rows = (
            await session.execute(text(FIELD_STATS_SQL), params)
        ).mappings().all()
        di_rows = (
            await session.execute(text(DI_AVAILABILITY_SQL), params)
        ).mappings().all()
        tenant_rows = (
            await session.execute(text(TENANT_BREAKDOWN_SQL), params)
        ).mappings().all()

    def _pct(num: int, den: int) -> float | None:
        return round(100.0 * num / den, 2) if den else None

    field_stats: list[dict[str, Any]] = []
    for row in field_rows:
        count = int(row["invoice_count"] or 0)
        field_stats.append(
            {
                "field": row["field_name"],
                "invoices": count,
                "di_chosen_pct": _pct(int(row["di_chosen"] or 0), count),
                "llm_chosen_pct": _pct(int(row["llm_chosen"] or 0), count),
                "agreed_pct": _pct(int(row["agreed_count"] or 0), count),
                "disagreed_both_pct": _pct(int(row["disagreed_both_present"] or 0), count),
                "di_had_value_pct": _pct(int(row["di_had_value"] or 0), count),
                "di_chosen": int(row["di_chosen"] or 0),
                "llm_chosen": int(row["llm_chosen"] or 0),
                "disagreed_both": int(row["disagreed_both_present"] or 0),
            }
        )

    di_summary = dict(di_rows[0]) if di_rows else {"invoice_count": 0, "di_available_count": 0}
    invoice_count = int(di_summary.get("invoice_count") or 0)
    di_available_count = int(di_summary.get("di_available_count") or 0)

    return {
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "provider": provider,
        "invoice_count": invoice_count,
        "di_availability": {
            "available_count": di_available_count,
            "available_pct": _pct(di_available_count, invoice_count),
        },
        "field_stats": field_stats,
        "tenant_breakdown_total_field": [dict(row) for row in tenant_rows],
        "notes": [
            "Requires field_resolution_telemetry audit events (LOG_FIELD_RESOLUTION_TELEMETRY=true).",
            "Historical invoices processed before telemetry deployment will not appear.",
            "policy_reextract events are excluded from primary stats.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="Lookback window when since/until omitted")
    parser.add_argument("--since", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--until", type=str, default=None, help="YYYY-MM-DD (inclusive end day)")
    parser.add_argument(
        "--provider",
        type=str,
        default="azure_foundry_vision",
        help="document_ai_provider filter",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of tables")
    args = parser.parse_args()

    if args.until:
        until = _parse_day(args.until, end=True)
    else:
        until = datetime.now(timezone.utc)
    if args.since:
        since = _parse_day(args.since)
    else:
        since = until - timedelta(days=max(args.days, 1))

    payload = asyncio.run(
        run_report(since=since, until=until, provider=args.provider.strip())
    )

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return

    print(
        f"DI dependency report ({payload['provider']}) "
        f"{payload['window']['since']} -> {payload['window']['until']}"
    )
    print(f"Invoices with telemetry: {payload['invoice_count']}")
    avail = payload["di_availability"]
    print(
        f"DI available on invoice: {avail['available_count']} "
        f"({avail['available_pct']}%)"
    )
    _print_table("Per-field stats", payload["field_stats"])
    _print_table("Per-tenant total field", payload["tenant_breakdown_total_field"])
    sql_path = Path(__file__).with_name("di_dependency_report.sql")
    print(f"\nRaw SQL reference: {sql_path}")


if __name__ == "__main__":
    main()
