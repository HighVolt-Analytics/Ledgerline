"""Xero Accounting API headers. Full request/retry is Stage 2+."""

from __future__ import annotations


def accounting_headers(*, access_token: str, xero_tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": xero_tenant_id,
        "Accept": "application/json",
    }
