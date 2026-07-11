import type { PlaybookProfile } from "@/lib/documentPlaybookConfig";
import type { ChartOfAccountRow } from "@/api/types";
import { filterCoaAccountsForPostingRole, resolveCoaAccountName } from "@/lib/coaAccountOptions";

export const SUGGESTED_LEDGER_BY_PLAYBOOK_PROFILE: Partial<Record<PlaybookProfile | string, string>> = {
  po_goods: "Raw Materials",
  import_dossier: "Raw Materials",
  freight_logistics: "Logistics",
  standard_transactional: "Operating Expenses",
  credit_adjustment: "Operating Expenses",
  debit_note: "Operating Expenses",
  direct_expense: "Operating Expenses",
  employee_claim: "Travel Expense",
  ar_goods: "Operating Revenue",
  pre_transactional: "Suspense Account",
};

const REVENUE_NAME_HINT = /\b(sales|revenue|income|turnover)\b/i;

function resolveSparseRevenueLedger(accounts: ChartOfAccountRow[]): string {
  const revenueAccounts = filterCoaAccountsForPostingRole(accounts, "revenue");
  if (revenueAccounts.length === 1) return revenueAccounts[0].name;
  const preferred = revenueAccounts.find((row) => REVENUE_NAME_HINT.test(row.name));
  return preferred?.name ?? "";
}

export function suggestedLedgerForPlaybookProfile(playbookProfile: string | undefined): string {
  const token = (playbookProfile ?? "").trim().toLowerCase();
  return SUGGESTED_LEDGER_BY_PLAYBOOK_PROFILE[token] ?? "";
}

export function defaultPostToLedger(
  playbookProfile: string | undefined,
  accounts: ChartOfAccountRow[],
  routeTarget?: string
): string {
  const profile = (playbookProfile ?? "").trim().toLowerCase();
  const route = (routeTarget ?? "").trim();
  const suggested = suggestedLedgerForPlaybookProfile(playbookProfile);
  if (suggested) {
    const resolved = resolveCoaAccountName(suggested, accounts);
    if (resolved) return resolved;
  }
  if (profile === "ar_goods" || route === "Sales Management") {
    return resolveSparseRevenueLedger(accounts);
  }
  return "";
}

export function applyDefaultPostToIfEmpty(
  postTo: { ledger: string; subLedger: string },
  playbookProfile: string | undefined,
  accounts: ChartOfAccountRow[],
  routeTarget?: string
): { ledger: string; subLedger: string } {
  if (postTo.ledger.trim()) return postTo;
  const ledger = defaultPostToLedger(playbookProfile, accounts, routeTarget);
  return ledger ? { ...postTo, ledger } : postTo;
}

export function defaultSalesRulePostTo(accounts: ChartOfAccountRow[]): {
  ledger: string;
  subLedger: string;
  taxAccount: string;
  receivableAccount: string;
} {
  const taxAccounts = filterCoaAccountsForPostingRole(accounts, "tax_collected");
  const receivableAccounts = filterCoaAccountsForPostingRole(accounts, "receivable");
  return {
    ledger: defaultPostToLedger("ar_goods", accounts),
    subLedger: "",
    taxAccount: taxAccounts[0]?.name ?? "",
    receivableAccount: receivableAccounts[0]?.name ?? "",
  };
}
