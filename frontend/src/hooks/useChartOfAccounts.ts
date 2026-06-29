import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ChartOfAccountRow } from "@/api/types";
import { queryKeys } from "@/lib/queryClient";

export function useChartOfAccounts(enabled = true) {
  return useQuery({
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
