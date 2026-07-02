"""Verify PostgreSQL tables have tenant_id where multi-tenant isolation requires it.

Usage (from backend/ with venv active):
    python scripts/check_tenant_id_columns.py

Exit code 0 = all checks passed, 1 = failures found.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg

# Tables that must have a tenant_id column (RLS + ORM tenant-scoped models).
EXPECTED_TENANT_TABLES: frozenset[str] = frozenset(
    {
        "users",
        "invoices",
        "vendor_registry",
        "vendor_masters",
        "employee_masters",
        "pending_vendors",
        "purchase_orders",
        "payments",
        "connected_mailboxes",
        "connected_whatsapp_accounts",
        "mailbox_connection_requests",
        "mailbox_sync_jobs",
        "audit_logs",
        "daily_reconciliations",
        "user_tenant_mappings",
        "tenant_modules",
        "email_verification_otp",
        "tenant_member_invites",
        "tenant_rule_book_configs",
        "line_items",
        "journal_entries",
        "goods_receipts",
        "meta_webhook_dedupe",
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

# Tables intentionally without tenant_id (global or infrastructure).
EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        "tenants",
        "auth_accounts",
        "alembic_version",
    }
)


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        from app.config import get_settings

        url = get_settings().database_url
    url = (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = None
    if "ssl" in query:
        sslmode = query.pop("ssl", ["require"])[0]
    if "sslmode" in query:
        sslmode = query.pop("sslmode", [sslmode or "require"])[0]
    new_query = urlencode({k: v[0] for k, v in query.items()})
    base = urlunparse(parsed._replace(query=new_query))
    if sslmode:
        sep = "&" if new_query else "?"
        return f"{base}{sep}sslmode={sslmode}"
    return base


def _fetch_tables(cur) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [row[0] for row in cur.fetchall()]


def _fetch_tenant_id_info(cur, table: str) -> dict | None:
    cur.execute(
        """
        SELECT
            c.data_type,
            c.udt_name,
            c.is_nullable,
            EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'tenant_id'
                  AND ccu.table_name = 'tenants'
                  AND ccu.column_name = 'id'
            ) AS fk_to_tenants
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name = %s
          AND c.column_name = 'tenant_id'
        """,
        (table, table),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "data_type": row[0],
        "udt_name": row[1],
        "is_nullable": row[2] == "YES",
        "fk_to_tenants": row[3],
    }


def _count_null_tenant_ids(cur, table: str) -> int:
    cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE tenant_id IS NULL')
    return int(cur.fetchone()[0])


def _count_orphan_tenant_ids(cur, table: str) -> int:
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM "{table}" t
        WHERE t.tenant_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM tenants tn WHERE tn.id = t.tenant_id
          )
        """
    )
    return int(cur.fetchone()[0])


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    with psycopg.connect(_sync_url()) as conn:
        with conn.cursor() as cur:
            tables = _fetch_tables(cur)
            print(f"Found {len(tables)} tables in public schema.\n")

            has_tenant: list[str] = []
            missing_expected: list[str] = []
            exempt_ok: list[str] = []
            unexpected_missing: list[str] = []
            unexpected_present: list[str] = []

            for table in tables:
                info = _fetch_tenant_id_info(cur, table)
                if info is not None:
                    has_tenant.append(table)
                    if table in EXEMPT_TABLES:
                        unexpected_present.append(table)
                    if info["udt_name"] != "uuid":
                        failures.append(
                            f"{table}.tenant_id has type {info['udt_name']!r}, expected uuid"
                        )
                    if table in EXPECTED_TENANT_TABLES and not info["fk_to_tenants"]:
                        warnings.append(
                            f"{table}.tenant_id has no FK to tenants.id"
                        )
                    if table in EXPECTED_TENANT_TABLES:
                        nulls = _count_null_tenant_ids(cur, table)
                        if nulls:
                            label = "warning" if info["is_nullable"] else "FAIL"
                            msg = f"{table}: {nulls} row(s) with NULL tenant_id"
                            if info["is_nullable"]:
                                warnings.append(msg)
                            else:
                                failures.append(msg)
                        orphans = _count_orphan_tenant_ids(cur, table)
                        if orphans:
                            failures.append(
                                f"{table}: {orphans} row(s) with tenant_id not in tenants"
                            )
                else:
                    if table in EXPECTED_TENANT_TABLES:
                        missing_expected.append(table)
                        failures.append(f"{table}: missing tenant_id column (required)")
                    elif table in EXEMPT_TABLES:
                        exempt_ok.append(table)
                    else:
                        unexpected_missing.append(table)
                        warnings.append(
                            f"{table}: no tenant_id (not in expected or exempt lists — review)"
                        )

            # Expected tables that do not exist yet (e.g. before migration).
            for table in sorted(EXPECTED_TENANT_TABLES - set(tables)):
                warnings.append(f"{table}: expected tenant table but not present in database")

            print("=== tenant_id present ===")
            for table in sorted(has_tenant):
                mark = ""
                if table in EXPECTED_TENANT_TABLES:
                    mark = " [expected]"
                elif table in EXEMPT_TABLES:
                    mark = " [unexpected — exempt list]"
                print(f"  OK  {table}{mark}")

            print("\n=== exempt (no tenant_id required) ===")
            for table in sorted(exempt_ok):
                print(f"  OK  {table}")

            if missing_expected:
                print("\n=== MISSING tenant_id (required) ===")
                for table in sorted(missing_expected):
                    print(f"  FAIL  {table}")

            if unexpected_missing:
                print("\n=== no tenant_id (unclassified) ===")
                for table in sorted(unexpected_missing):
                    print(f"  ??  {table}")

            if unexpected_present:
                print("\n=== tenant_id on exempt table ===")
                for table in sorted(unexpected_present):
                    print(f"  ??  {table}")

            print("\n=== summary ===")
            print(f"  tables checked:        {len(tables)}")
            print(f"  with tenant_id:        {len(has_tenant)}")
            print(f"  expected w/ tenant_id: {len(EXPECTED_TENANT_TABLES & set(tables))}")
            print(f"  exempt w/o tenant_id:  {len(EXEMPT_TABLES & set(tables))}")
            print(f"  failures:              {len(failures)}")
            print(f"  warnings:              {len(warnings)}")

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
