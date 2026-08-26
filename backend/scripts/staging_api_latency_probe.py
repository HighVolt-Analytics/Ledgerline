"""In-cluster staging API latency probe.

Run inside the API pod (has JWT secret + DB). Prints path/status/durations only —
no tokens, emails, or tenant names.

  kubectl cp backend/scripts/staging_api_latency_probe.py \\
    quantum-ledgerlink/<api-pod>:/tmp/staging_api_latency_probe.py
  kubectl exec -n quantum-ledgerlink <api-pod> -- \\
    python /tmp/staging_api_latency_probe.py
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

from sqlalchemy import func, select

from app.database import async_session_factory, dispose_engine
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth.auth_service import create_access_token
from app.tenant_rls import apply_platform_lookup_session

BASE = "http://127.0.0.1:8001"
SAMPLES = 5
TIMEOUT_S = 20

# First-paint + chrome APIs. Staging may be older than local; 404 is still a result.
PATHS: tuple[str, ...] = (
    "/health",
    "/api/auth/me",
    "/api/auth/me/permissions",
    "/api/dashboard/badges",
    "/api/notifications?limit=30",
    "/api/dashboard/overview?month=2026-08&activity_limit=10",
    "/api/matrix?page=1&page_size=10",
    "/api/process/status",
    "/api/mailboxes",
    "/api/vault/tree",
    "/api/vault/tree?file_limit=50",
    "/api/vault/document-sets",
    "/api/invoices?page=1&page_size=100&route_target=Vault",
    "/api/approvals/board",
    "/api/rule-book/config",
    "/api/rule-book/config?fields=editor",
    "/api/purchases",
    "/api/purchases/kpis",
    "/api/sales",
    "/api/sales/kpis",
    "/api/collections?status=queue&limit=50",
    "/api/collections/kpis",
    "/api/payments?status=queue&limit=50",
    "/api/payments/kpis",
    "/api/ledger-link",
    "/api/ledger-link?fields=overview",
    "/api/reports/analytics?month=2026-08",
    "/api/reports/team-expenses/workspace-kpis",
    "/api/reports/expenses/workspace-kpis",
    "/api/employee-masters",
    "/api/invoices?page=1&page_size=10",
)


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def _hit(path: str, headers: dict[str, str]) -> dict[str, object]:
    req = urllib.request.Request(f"{BASE}{path}", headers=headers, method="GET")
    started = time.perf_counter()
    status = 0
    error = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        exc.read()
        status = int(exc.code)
    except Exception as exc:  # noqa: BLE001 — probe must record failures
        error = type(exc).__name__
    ms = round((time.perf_counter() - started) * 1000.0, 1)
    row: dict[str, object] = {"status": status, "ms": ms}
    if error:
        row["error"] = error
    return row


async def _mint_headers() -> dict[str, str]:
    inv_counts = (
        select(Invoice.tenant_id, func.count().label("n"))
        .group_by(Invoice.tenant_id)
        .subquery()
    )
    async with async_session_factory() as session:
        await apply_platform_lookup_session(session)
        row = (
            await session.execute(
                select(User, Tenant, inv_counts.c.n)
                .join(Tenant, User.tenant_id == Tenant.id)
                .outerjoin(inv_counts, inv_counts.c.tenant_id == Tenant.id)
                .where(
                    Tenant.is_platform.is_(False),
                    Tenant.is_active.is_(True),
                    User.is_active.is_(True),
                    User.role != UserRole.SUPER_ADMIN,
                )
                .order_by(inv_counts.c.n.desc().nulls_last())
                .limit(1)
            )
        ).first()
        if row is None:
            raise RuntimeError("no non-platform tenant user")
        user, tenant, invoice_count = row
        token = create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            email=user.email,
            role=user.role.value,
        )
        print(
            json.dumps(
                {
                    "tenant_kind": "non_platform",
                    "invoice_count": int(invoice_count or 0),
                    "role": user.role.value,
                }
            ),
            flush=True,
        )
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-Id": str(tenant.id),
            "Accept": "application/json",
        }


async def main() -> None:
    headers = await _mint_headers()
    results: list[dict[str, object]] = []
    for path in PATHS:
        samples = [_hit(path, headers) for _ in range(SAMPLES)]
        times = [float(s["ms"]) for s in samples]
        statuses = [int(s["status"]) for s in samples]
        errors = [str(s["error"]) for s in samples if "error" in s]
        results.append(
            {
                "path": path,
                "n": SAMPLES,
                "statuses": statuses,
                "ms": times,
                "p50_ms": round(_pct(times, 50), 1),
                "p95_ms": round(_pct(times, 95), 1),
                "max_ms": round(max(times), 1),
                "under_1s": max(times) < 1000.0,
                "errors": errors,
            }
        )
        print(json.dumps(results[-1]), flush=True)

    over = [r for r in results if not r["under_1s"] or r["errors"]]
    print(
        json.dumps(
            {
                "summary": {
                    "paths": len(results),
                    "under_1s": sum(1 for r in results if r["under_1s"]),
                    "over_1s_or_error": len(over),
                    "over_paths": [r["path"] for r in over],
                }
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    async def _run() -> None:
        try:
            await main()
        finally:
            await dispose_engine()

    asyncio.run(_run())
