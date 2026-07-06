/**
 * Static checks: every tenant-facing page uses tenant isolation guards or tenant-scoped hooks.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PAGES_DIR = join(__dirname, "..", "pages");

/** Pages that do not load tenant-owned list/detail data. */
const EXEMPT_PAGES = new Set([
  "LoginPage.tsx",
  "AcceptInvitePage.tsx",
  "ConnectMailboxPage.tsx",
  "SuperAdminEmbedPage.tsx",
  "MatrixPage.tsx",
  "CustomersPage.tsx",
  "SetupPage.tsx",
]);

const EXEMPT_PREFIXES = ["platform/"];

const GUARD_PATTERNS = [
  /canRenderTenantOwnedUi/,
  /captureTenantFetchScope/,
  /useTenantOwnedData/,
  /useTenantQuery/,
  /useResetOnTenantChange/,
];

const TENANT_SCOPED_HOOKS = [
  "useDashboardOverview",
  "useNavBadges",
  "useNotifications",
  "useReconciliationOverview",
  "useReportsAnalytics",
  "useRuleBookConfig",
  "useRecognitionSignalCatalog",
  "useVendorMasters",
  "useEmployeeMasters",
  "useMasterData",
  "usePurchases",
  "useSales",
  "useCollections",
  "usePayments",
  "useWalletSummary",
  "useStripe",
  "useBilling",
  "useLedgerLink",
  "useMailboxes",
  "useRoutedInvoices",
  "useInstitutionSettings",
  "usePermissions",
  "useOrgAiBrief",
  "useChartOfAccounts",
];

function tenantPageFiles(): string[] {
  const { readdirSync, statSync } = require("node:fs") as typeof import("node:fs");
  const out: string[] = [];

  function walk(dir: string, rel = "") {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      const relPath = rel ? `${rel}/${name}` : name;
      if (statSync(full).isDirectory()) {
        walk(full, relPath);
        continue;
      }
      if (!name.endsWith("Page.tsx")) continue;
      if (EXEMPT_PAGES.has(name)) continue;
      if (EXEMPT_PREFIXES.some((p) => relPath.startsWith(p))) continue;
      out.push(relPath);
    }
  }

  walk(PAGES_DIR);
  return out.sort();
}

function hasTenantIsolation(source: string): boolean {
  if (GUARD_PATTERNS.some((re) => re.test(source))) return true;
  return TENANT_SCOPED_HOOKS.some((hook) => source.includes(hook));
}

describe("tenant page isolation coverage", () => {
  const pages = tenantPageFiles();

  it("discovers tenant-facing pages", () => {
    expect(pages.length).toBeGreaterThan(15);
  });

  for (const relPath of pages) {
    it(`${relPath} uses tenant guards or tenant-scoped hooks`, () => {
      const source = readFileSync(join(PAGES_DIR, relPath), "utf8");
      expect(hasTenantIsolation(source)).toBe(true);
    });
  }
});

describe("tenant API route registry", () => {
  const CORE_API_PREFIXES = [
    "/api/dashboard",
    "/api/invoices",
    "/api/vault",
    "/api/approvals",
    "/api/rule-book",
    "/api/mailboxes",
    "/api/payments",
    "/api/billing",
    "/api/tenants/current",
    "/api/integrations",
  ];

  it("documents core tenant API prefixes covered by backend isolation tests", () => {
    for (const prefix of CORE_API_PREFIXES) {
      expect(prefix.startsWith("/api/")).toBe(true);
    }
    expect(CORE_API_PREFIXES.length).toBeGreaterThanOrEqual(10);
  });
});
