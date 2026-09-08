/** Canonical tenant module catalog. Keep in sync with backend/app/tenant_modules.py */

export type TenantModuleGroup = "Workspace" | "Operations" | "Finance";

export type TenantModuleDef = {
  key: string;
  label: string;
  description: string;
  group: TenantModuleGroup;
};

export const TENANT_MODULE_CATALOG: TenantModuleDef[] = [
  {
    key: "purchase",
    label: "Purchase Management",
    description: "Purchase orders, GRN, and three-way match.",
    group: "Workspace",
  },
  {
    key: "sales",
    label: "Sales Management",
    description: "Customer invoices, receivables, and sales GL coding.",
    group: "Workspace",
  },
  {
    key: "expenses",
    label: "Expenses Management",
    description: "Business expense claims routed from the rule book.",
    group: "Workspace",
  },
  {
    key: "team_expenses",
    label: "Team Expenses",
    description: "Employee expense claims and budgets.",
    group: "Workspace",
  },
  {
    key: "rule_book",
    label: "Rule Book",
    description: "Routing rules and expense categories.",
    group: "Operations",
  },
  {
    key: "vault",
    label: "Vault",
    description: "Stored invoice files and folder tree.",
    group: "Finance",
  },
  {
    key: "payments",
    label: "Payments",
    description: "Payment queue and disbursement.",
    group: "Finance",
  },
  {
    key: "bank_feeds",
    label: "Bank Feeds",
    description: "Bank statement import and cash reconciliation.",
    group: "Workspace",
  },
  {
    key: "ledger_link",
    label: "Ledger Sync",
    description: "Export to accounting ledger.",
    group: "Finance",
  },
  {
    key: "reports",
    label: "Reports",
    description: "Financial and operational reports.",
    group: "Finance",
  },
];

export const MODULE_GROUP_ORDER: TenantModuleGroup[] = [
  "Workspace",
  "Operations",
  "Finance",
];

/** Nav path → module key. Paths without an entry are always on. */
export const PATH_TO_MODULE: Record<string, string> = {
  "/purchases": "purchase",
  "/sales": "sales",
  "/expenses": "expenses",
  "/team-expenses": "team_expenses",
  "/rules": "rule_book",
  "/vault": "vault",
  "/payments": "payments",
  "/bank-feeds": "bank_feeds",
  "/ledger-link": "ledger_link",
  "/reports": "reports",
};

export function canAccessModulePath(
  path: string,
  enabledModules: Record<string, boolean> | null | undefined,
  moduleKey?: string
): boolean {
  const key = moduleKey ?? PATH_TO_MODULE[path];
  if (!key) return true;
  if (!enabledModules) return true;
  return enabledModules[key] !== false;
}

export function modulesFromApi(
  rows: { module_key: string; is_active: boolean }[]
): Record<string, boolean> {
  const fromApi = Object.fromEntries(rows.map((m) => [m.module_key, m.is_active]));
  return Object.fromEntries(
    TENANT_MODULE_CATALOG.map((m) => [m.key, fromApi[m.key] ?? true])
  );
}
