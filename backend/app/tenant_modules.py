"""Canonical tenant module catalog. Keep in sync with frontend/src/lib/tenantModules.ts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantModuleDef:
    key: str
    label: str
    description: str
    group: str
    default_active: bool = True
    always_on: bool = False


TENANT_MODULE_CATALOG: tuple[TenantModuleDef, ...] = (
    TenantModuleDef(
        key="purchase",
        label="Purchase Management",
        description="Purchase orders, GRN, and three-way match.",
        group="Workspace",
    ),
    TenantModuleDef(
        key="expenses",
        label="Expenses Management",
        description="Business expense claims routed from the rule book.",
        group="Workspace",
    ),
    TenantModuleDef(
        key="team_expenses",
        label="Team Expenses",
        description="Employee expense claims and budgets.",
        group="Workspace",
    ),
    TenantModuleDef(
        key="rule_book",
        label="Rule Book",
        description="Routing rules and expense categories.",
        group="Operations",
    ),
    TenantModuleDef(
        key="dossiers",
        label="Dossiers",
        description="Purchase dossiers and approval chains.",
        group="Operations",
    ),
    TenantModuleDef(
        key="vault",
        label="Vault",
        description="Stored invoice files and folder tree.",
        group="Finance",
    ),
    TenantModuleDef(
        key="payments",
        label="Payments",
        description="Payment queue and disbursement.",
        group="Finance",
    ),
    TenantModuleDef(
        key="ledger_link",
        label="Ledger Link",
        description="Export to accounting ledger.",
        group="Finance",
    ),
    TenantModuleDef(
        key="reports",
        label="Reports",
        description="Financial and operational reports.",
        group="Finance",
    ),
)

CATALOG_BY_KEY: dict[str, TenantModuleDef] = {m.key: m for m in TENANT_MODULE_CATALOG}
CATALOG_KEYS: frozenset[str] = frozenset(CATALOG_BY_KEY)
TOGGLEABLE_MODULE_KEYS: tuple[str, ...] = tuple(m.key for m in TENANT_MODULE_CATALOG if not m.always_on)
