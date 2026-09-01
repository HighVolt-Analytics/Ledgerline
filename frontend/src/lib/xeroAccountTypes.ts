import type { ChartOfAccountType } from "@/api/types";

export const XERO_SUBTYPES_BY_TYPE: Record<
  ChartOfAccountType,
  { value: string; label: string }[]
> = {
  Asset: [
    { value: "CURRENT", label: "Current Asset" },
    { value: "BANK", label: "Bank" },
    { value: "FIXED", label: "Fixed Asset" },
    { value: "NONCURRENT", label: "Non-current Asset" },
    { value: "INVENTORY", label: "Inventory" },
    { value: "PREPAYMENT", label: "Prepayment" },
  ],
  Liability: [
    { value: "CURRLIAB", label: "Current Liability" },
    { value: "TERMLIAB", label: "Non-current Liability" },
    { value: "LIABILITY", label: "Liability" },
  ],
  Equity: [{ value: "EQUITY", label: "Equity" }],
  Revenue: [
    { value: "REVENUE", label: "Revenue" },
    { value: "SALES", label: "Sales" },
    { value: "OTHERINCOME", label: "Other Income" },
  ],
  Expense: [
    { value: "EXPENSE", label: "Expense" },
    { value: "DIRECTCOSTS", label: "Direct Costs" },
    { value: "OVERHEADS", label: "Overhead" },
    { value: "DEPRECIATN", label: "Depreciation" },
  ],
};

export const DEFAULT_XERO_SUBTYPE: Record<ChartOfAccountType, string> = {
  Asset: "CURRENT",
  Liability: "CURRLIAB",
  Equity: "EQUITY",
  Revenue: "REVENUE",
  Expense: "EXPENSE",
};

export function xeroSubtypeOptions(type: ChartOfAccountType) {
  return XERO_SUBTYPES_BY_TYPE[type];
}

export function defaultXeroSubtype(type: ChartOfAccountType): string {
  return DEFAULT_XERO_SUBTYPE[type];
}

export function normalizeXeroSubtype(type: ChartOfAccountType, subtype: string | null | undefined): string {
  const allowed = new Set(XERO_SUBTYPES_BY_TYPE[type].map((item) => item.value));
  const cleaned = (subtype ?? "").trim().toUpperCase();
  if (allowed.has(cleaned)) return cleaned;
  return defaultXeroSubtype(type);
}

export function xeroSubtypeLabel(type: ChartOfAccountType, subtype: string): string {
  return XERO_SUBTYPES_BY_TYPE[type].find((item) => item.value === subtype)?.label ?? subtype;
}
