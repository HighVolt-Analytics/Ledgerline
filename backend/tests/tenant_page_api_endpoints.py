"""GET endpoints used by tenant-facing app pages — for header isolation tests."""

from __future__ import annotations

# Every path must be tenant-scoped (require_user + X-Tenant-Id when AUTH_REQUIRED).
TENANT_PAGE_GET_PATHS: tuple[str, ...] = (
    # Dashboard
    "/api/dashboard/badges",
    "/api/dashboard/stats",
    "/api/dashboard/overview?month=2026-01&activity_limit=5",
    "/api/dashboard/activity?limit=10",
    # Upload / matrix / invoices
    "/api/invoices?page_size=10",
    "/api/invoices/classification-review",
    "/api/matrix",
    "/api/process/status",
    "/api/mailboxes",
    "/api/mailboxes/requests",
    # Vault
    "/api/vault/tree",
    # Approvals
    "/api/approvals",
    "/api/approvals/board",
    "/api/approval-policy",
    # Rule book / rules page
    "/api/rule-book/config",
    "/api/rule-book/changelog",
    "/api/rule-book/recognition-signals",
    "/api/rule-book/ai-providers",
    # Vendors / customers (pages + rule book tabs)
    "/api/vendors",
    "/api/vendor-masters",
    "/api/pending-vendors",
    "/api/customers",
    "/api/customer-masters",
    "/api/employee-masters",
    # Reports
    "/api/reports/analytics?month=2026-01",
    "/api/reports/documents",
    # Reconciliation
    "/api/reconciliation/overview",
    "/api/reconciliation/daily",
    # Settings / team
    "/api/tenants/current/members",
    "/api/tenants/current/institution",
    "/api/tenants/current/org-ai-brief",
    "/api/tenants/current/chart-of-accounts",
    "/api/tenants/current/onboarding",
    "/api/auth/me",
    "/api/auth/me/permissions",
    # Integrations (settings is public — not tenant-scoped)
    "/api/integrations/status",
    "/api/integrations/whatsapp/status",
    "/api/integrations/viber/status",
    # Workspace modules
    "/api/purchases",
    "/api/sales",
    "/api/collections",
    "/api/payments",
    "/api/payments/wallet-summary",
    "/api/payments/stripe/readiness",
    "/api/payments/stripe/global-payouts/readiness",
    "/api/dossiers",
    "/api/ledger-link",
    "/api/billing",
    "/api/billing/usage?page=1&page_size=10",
    # Ops
    "/api/notifications",
    "/api/audit-log?page_size=10",
)

# Subset that must return 200 with a valid admin token (no optional missing resource).
TENANT_PAGE_GET_PATHS_EXPECT_200: tuple[str, ...] = tuple(
    p
    for p in TENANT_PAGE_GET_PATHS
    if not p.startswith("/api/payments/stripe/account")
)
