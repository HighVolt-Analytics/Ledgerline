import type { ChartOfAccountRow, ChartOfAccountType } from "@/api/types";

export type CoaSelectOption = { value: string; label: string };

export function formatCoaAccountLabel(row: ChartOfAccountRow): string {
  const code = row.code.trim();
  const name = row.name.trim();
  if (code && name) return `${code} · ${name}`;
  return name || code;
}

export function resolveCoaAccountName(
  suggested: string,
  accounts: ChartOfAccountRow[]
): string {
  const needle = suggested.trim();
  if (!needle || !accounts.length) return "";
  for (const row of accounts) {
    if (row.name === needle) return row.name;
  }
  const lowered = needle.toLowerCase();
  for (const row of accounts) {
    if (row.name.toLowerCase() === lowered) return row.name;
  }
  for (const row of accounts) {
    const nameLower = row.name.toLowerCase();
    if (lowered.includes(nameLower) || nameLower.includes(lowered)) return row.name;
  }
  return "";
}

export function ledgerExistsInCoa(ledger: string, accounts: ChartOfAccountRow[]): boolean {
  return Boolean(resolveCoaAccountName(ledger, accounts) || accounts.some((row) => row.name === ledger.trim()));
}

export function coaAccountsToSelectOptions(
  accounts: ChartOfAccountRow[],
  { includeEmpty = false, emptyLabel = "— Select account —" }: { includeEmpty?: boolean; emptyLabel?: string } = {}
): CoaSelectOption[] {
  const rows = [...accounts].sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
  const options = rows.map((row) => ({
    value: row.name,
    label: formatCoaAccountLabel(row),
  }));
  if (includeEmpty) {
    return [{ value: "", label: emptyLabel }, ...options];
  }
  return options;
}

export function filterCoaAccountsByTypes(
  accounts: ChartOfAccountRow[],
  types: ChartOfAccountType[] | undefined
): ChartOfAccountRow[] {
  if (!types?.length) return accounts;
  const allowed = new Set(types);
  return accounts.filter((row) => allowed.has(row.type));
}

export function coaTypesForRouteTarget(routeTarget: string): ChartOfAccountType[] | undefined {
  switch (routeTarget) {
    case "Sales Management":
      return undefined;
    case "Purchase Management":
    case "Expenses Management":
    case "Team Expenses":
      return ["Expense", "Asset"];
    default:
      return undefined;
  }
}

export function coaTypesForMainLedger(
  playbookProfile: string,
  routeTarget?: string
): ChartOfAccountType[] | undefined {
  const profile = playbookProfile.trim().toLowerCase();
  const route = (routeTarget ?? "").trim();
  if (profile === "ar_goods") return ["Revenue"];
  if (profile === "po_goods" || profile === "import_dossier") return ["Expense", "Asset"];
  if (profile === "pre_transactional") return ["Liability"];
  if (
    profile === "supporting" ||
    profile === "non_actionable" ||
    profile === "informational" ||
    profile === "master_data" ||
    profile === "compliance_route" ||
    profile === "reconciliation"
  ) {
    return undefined;
  }
  if (profile) return ["Expense"];
  if (route === "Sales Management") return ["Revenue"];
  if (route === "Purchase Management" || route === "Expenses Management" || route === "Team Expenses") {
    return ["Expense", "Asset"];
  }
  return undefined;
}

/** Trade debtors / AR — asset accounts only. */
export function coaTypesForSalesReceivable(): ChartOfAccountType[] {
  return ["Asset"];
}

/** Output tax (GST collected) — liability accounts only. */
export function coaTypesForSalesTax(): ChartOfAccountType[] {
  return ["Liability"];
}

export function coaTypesForTaxDefaults(): ChartOfAccountType[] {
  return ["Asset", "Liability"];
}

export function coaTypesForPayableDefaults(): ChartOfAccountType[] {
  return ["Liability"];
}

export function coaTypesForFallbackDefaults(): ChartOfAccountType[] {
  return ["Expense", "Liability", "Asset"];
}

export type CoaPostingRole = "revenue" | "receivable" | "tax_collected";

const REVENUE_LIKE_NAME = /\b(sales|revenue|income|turnover)\b/i;
const RECEIVABLE_LIKE_NAME = /\b(receivable|debtor|debtors|trade)\b/i;
const TAX_COLLECTED_LIKE_NAME = /\b(gst|tax|vat|output)\b/i;

export function isRevenueLikeAccountName(name: string): boolean {
  return REVENUE_LIKE_NAME.test(name.trim());
}

export function isReceivableLikeAccountName(name: string): boolean {
  return RECEIVABLE_LIKE_NAME.test(name.trim());
}

export function isTaxCollectedLikeAccountName(name: string): boolean {
  return TAX_COLLECTED_LIKE_NAME.test(name.trim());
}

export function excludeCoaAccountNames(
  accounts: ChartOfAccountRow[],
  namesToExclude: string[]
): ChartOfAccountRow[] {
  const excluded = new Set(namesToExclude.map((name) => name.trim()).filter(Boolean));
  if (!excluded.size) return accounts;
  return accounts.filter((row) => !excluded.has(row.name));
}

export function filterCoaAccountsForPostingRole(
  accounts: ChartOfAccountRow[],
  role: CoaPostingRole | undefined
): ChartOfAccountRow[] {
  if (!role) return accounts;

  switch (role) {
    case "revenue":
      return accounts.filter(
        (row) =>
          row.type === "Revenue" &&
          !isReceivableLikeAccountName(row.name) &&
          !isTaxCollectedLikeAccountName(row.name)
      );
    case "receivable":
      return accounts.filter(
        (row) =>
          row.type === "Asset" &&
          isReceivableLikeAccountName(row.name) &&
          !isRevenueLikeAccountName(row.name)
      );
    case "tax_collected":
      return accounts.filter(
        (row) =>
          row.type === "Liability" &&
          isTaxCollectedLikeAccountName(row.name) &&
          !isRevenueLikeAccountName(row.name)
      );
    default:
      return accounts;
  }
}

export function postingRoleForMainLedger(
  playbookProfile: string,
  routeTarget?: string
): CoaPostingRole | undefined {
  const types = coaTypesForMainLedger(playbookProfile, routeTarget);
  if (types?.length === 1 && types[0] === "Revenue") return "revenue";
  return undefined;
}
