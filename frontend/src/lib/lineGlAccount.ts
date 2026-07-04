import type { InvoiceDetails, LineItem } from "@/api/types";

export const EXPENSE_GL_ACCOUNTS = [
  "Raw Materials",
  "Freight & Logistics",
  "Office Supplies",
  "Professional Services",
  "Contractor Costs",
  "Utilities",
  "Suspense Account",
] as const;

export function suggestLineAccount(
  inv: Pick<InvoiceDetails, "account_name">,
  line: Pick<LineItem, "description">,
  postingApplies: boolean,
): string {
  if (!postingApplies) return "Not posted — reference document";
  const desc = (line.description ?? "").toLowerCase();
  if (
    desc.includes("steel") ||
    desc.includes("coil") ||
    desc.includes("sheet") ||
    desc.includes("material")
  ) {
    return "Raw Materials";
  }
  if (desc.includes("freight") || desc.includes("logistics") || desc.includes("shipping")) {
    return "Freight & Logistics";
  }
  if (desc.includes("consult") || desc.includes("freelance") || desc.includes("development")) {
    return "Professional Services";
  }
  return inv.account_name ?? "Suspense Account";
}

export function lineAccountReason(account: string, vendor: string | null): string {
  if (account === "Not posted — reference document") {
    return "Supporting / compliance document — no ledger entry";
  }
  if (account === "Suspense Account") return "Awaiting rule book mapping";
  const who = vendor ?? "vendor";
  if (account === "Raw Materials") return `${account} match: ${who} vendor rule`;
  return `${account} match: ${who} keyword rule`;
}

export function mergeGlAccountOptions(
  suggested: string,
  invoiceAccountName: string | null | undefined,
  coaAccountNames: string[],
): string[] {
  return Array.from(
    new Set(
      [
        suggested,
        invoiceAccountName,
        ...coaAccountNames,
        ...EXPENSE_GL_ACCOUNTS,
        "Suspense Account",
      ].filter((value): value is string => Boolean(value)),
    ),
  );
}
