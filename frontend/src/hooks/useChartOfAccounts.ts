import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ChartOfAccountRow } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useChartOfAccounts(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.chartOfAccounts(),
    queryFn: async () => {
      const res = await api.getChartOfAccounts();
      return (res.accounts ?? []).map((row) => ({
        ...row,
        type: normalizeChartOfAccountType(row.type),
      }));
    },
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
  });
}

export function useSaveChartOfAccounts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accounts: ChartOfAccountRow[]) =>
      (await api.updateChartOfAccounts({ accounts })).accounts ?? [],
    onSuccess: async (accounts) => {
      queryClient.setQueryData(queryKeys.chartOfAccounts(), accounts);
      await queryClient.refetchQueries({ queryKey: queryKeys.chartOfAccounts() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookConfig() });
    },
  });
}

export function newChartOfAccountRow(): ChartOfAccountRow {
  return { code: "", name: "", type: "Expense" };
}

export const CHART_OF_ACCOUNT_TYPES = [
  "Expense",
  "Asset",
  "Liability",
  "Revenue",
  "Equity",
] as const;

export type ChartOfAccountTypeOption = (typeof CHART_OF_ACCOUNT_TYPES)[number];

export function normalizeChartOfAccountType(value: string | undefined): ChartOfAccountTypeOption {
  const cleaned = (value ?? "").trim();
  return CHART_OF_ACCOUNT_TYPES.includes(cleaned as ChartOfAccountTypeOption)
    ? (cleaned as ChartOfAccountTypeOption)
    : "Expense";
}

export function inferChartOfAccountTypeFromName(name: string): ChartOfAccountTypeOption {
  const lower = name.trim().toLowerCase();
  if (!lower) return "Expense";
  if (/\b(receivable|debtor|debtors|trade)\b/.test(lower)) return "Asset";
  if (/\b(payable|suspense|gst collected|tax collected|output tax)\b/.test(lower)) return "Liability";
  if (/\b(gst paid|bank)\b/.test(lower)) return "Asset";
  if (/\b(sales|revenue|income|turnover)\b/.test(lower)) return "Revenue";
  if (/\b(equity|retained)\b/.test(lower)) return "Equity";
  return "Expense";
}

export function coaTypeMisclassificationWarnings(accounts: ChartOfAccountRow[]): string[] {
  const warnings: string[] = [];
  for (const row of accounts) {
    const name = row.name.trim();
    if (!name) continue;
    if (/\b(sales|revenue|income|turnover)\b/i.test(name) && row.type !== "Revenue") {
      warnings.push(`"${name}" looks like revenue but is typed ${row.type}.`);
    }
    if (/\b(receivable|debtor|debtors)\b/i.test(name) && row.type !== "Asset") {
      warnings.push(`"${name}" looks like a receivable but is typed ${row.type}.`);
    }
  }
  return warnings;
}
