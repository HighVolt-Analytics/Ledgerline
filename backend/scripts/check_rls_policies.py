"""Audit PostgreSQL tenant RLS coverage for all tenant-scoped tables.

Usage (from backend/ with venv active):
    python scripts/check_rls_policies.py

Exit code 0 = all checks passed, 1 = failures found.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

from check_tenant_id_columns import EXPECTED_TENANT_TABLES, EXEMPT_TABLES, _sync_url

# Tables with tenant_id that were added in later migrations (also in apply_tenant_rls.sql).
EXTRA_TENANT_RLS_TABLES: frozenset[str] = frozenset(
    {
        "dossier_manual_links",
        "stripe_accounts",
        "stripe_balance_snapshots",
        "stripe_transactions",
        "vendor_payment_methods",
        "invoice_ocr_artifacts",
        "classification_learning_events",
        "accounting_integrations",
        "connected_viber_accounts",
        "payment_execution_instructions",
        "customer_masters",
        "customer_registry",
        "sales_orders",
        "delivery_notes",
        "collections",
    }
)

REQUIRED_RLS_TABLES = EXPECTED_TENANT_TABLES | EXTRA_TENANT_RLS_TABLES


def _fetch_rls_status(cur, table: str) -> dict | None:
    cur.execute(
        """
        SELECT
            c.relrowsecurity AS rls_enabled,
            c.relforcerowsecurity AS rls_forced,
            EXISTS (
                SELECT 1
                FROM pg_policies p
                WHERE p.schemaname = 'public'
                  AND p.tablename = %s
                  AND p.policyname = 'tenant_isolation'
            ) AS has_tenant_policy
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = %s
          AND c.relkind = 'r'
        """,
        (table, table),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "rls_enabled": bool(row[0]),
        "rls_forced": bool(row[1]),
        "has_tenant_policy": bool(row[2]),
    }


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    with psycopg.connect(_sync_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            tables = {row[0] for row in cur.fetchall()}

            print(f"Required tenant RLS tables: {len(REQUIRED_RLS_TABLES)}")
            print(f"Tables present in database: {len(tables)}\n")

            for table in sorted(REQUIRED_RLS_TABLES):
                if table not in tables:
                    warnings.append(f"{table}: expected but table not present (run migrations first)")
                    continue
                status = _fetch_rls_status(cur, table)
                if status is None:
                    failures.append(f"{table}: could not read RLS status")
                    continue
                if not status["rls_enabled"]:
                    failures.append(f"{table}: ROW LEVEL SECURITY not enabled")
                if not status["has_tenant_policy"]:
                    failures.append(f"{table}: missing policy tenant_isolation")
                if not status["rls_forced"]:
                    warnings.append(
                        f"{table}: RLS enabled but not FORCED (table owner can bypass)"
                    )
                mark = "OK" if (
                    status["rls_enabled"]
                    and status["has_tenant_policy"]
                    and status["rls_forced"]
                ) else "!!"
                print(
                    f"  {mark}  {table}"
                    f"  enabled={status['rls_enabled']}"
                    f"  forced={status['rls_forced']}"
                    f"  policy={status['has_tenant_policy']}"
                )

            unclassified_with_tenant: list[str] = []
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name = 'tenant_id'
                ORDER BY table_name
                """
            )
            for (table,) in cur.fetchall():
                if table in REQUIRED_RLS_TABLES or table in EXEMPT_TABLES:
                    continue
                unclassified_with_tenant.append(table)
                warnings.append(
                    f"{table}: has tenant_id but is not in REQUIRED_RLS_TABLES or EXEMPT_TABLES"
                )

            if unclassified_with_tenant:
                print("\n=== tenant_id tables not classified ===")
                for table in unclassified_with_tenant:
                    print(f"  ??  {table}")

            print("\n=== summary ===")
            print(f"  failures:  {len(failures)}")
            print(f"  warnings:  {len(warnings)}")

            if failures:
                print("\nFailures:")
                for msg in failures:
                    print(f"  - {msg}")
            if warnings:
                print("\nWarnings:")
                for msg in warnings:
                    print(f"  - {msg}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
