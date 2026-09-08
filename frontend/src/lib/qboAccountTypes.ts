import type { ChartOfAccountType } from "@/api/types";

export const QBO_ACCOUNT_TYPES_BY_TYPE: Record<
  ChartOfAccountType,
  { value: string; label: string }[]
> = {
  Asset: [
    { value: "Other Current Asset", label: "Other Current Asset" },
    { value: "Fixed Asset", label: "Fixed Asset" },
    { value: "Other Asset", label: "Other Asset" },
    { value: "Bank", label: "Bank (create in QuickBooks)" },
    { value: "Accounts Receivable", label: "Accounts Receivable" },
  ],
  Liability: [
    { value: "Other Current Liability", label: "Other Current Liability" },
    { value: "Long Term Liability", label: "Long Term Liability" },
    { value: "Accounts Payable", label: "Accounts Payable" },
    { value: "Credit Card", label: "Credit Card (create in QuickBooks)" },
  ],
  Equity: [{ value: "Equity", label: "Equity" }],
  Revenue: [
    { value: "Income", label: "Income" },
    { value: "Other Income", label: "Other Income" },
  ],
  Expense: [
    { value: "Expense", label: "Expense" },
    { value: "Other Expense", label: "Other Expense" },
    { value: "Cost of Goods Sold", label: "Cost of Goods Sold" },
  ],
};

export const DEFAULT_QBO_ACCOUNT_TYPE: Record<ChartOfAccountType, string> = {
  Asset: "Other Current Asset",
  Liability: "Other Current Liability",
  Equity: "Equity",
  Revenue: "Income",
  Expense: "Expense",
};

export function qboAccountTypeOptions(type: ChartOfAccountType) {
  return QBO_ACCOUNT_TYPES_BY_TYPE[type];
}

export function defaultQboAccountType(type: ChartOfAccountType): string {
  return DEFAULT_QBO_ACCOUNT_TYPE[type];
}

export function normalizeQboAccountType(
  type: ChartOfAccountType,
  accountType: string | null | undefined
): string {
  const allowed = new Set(QBO_ACCOUNT_TYPES_BY_TYPE[type].map((item) => item.value));
  const cleaned = (accountType ?? "").trim();
  if (allowed.has(cleaned)) return cleaned;
  return defaultQboAccountType(type);
}
