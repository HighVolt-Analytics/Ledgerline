import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useTeamExpenseAdvanceSettlement(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.teAdvanceSettlement(),
    queryFn: () => api.getTeamExpenseAdvanceSettlement(),
    enabled,
  });
}

export function useTeamExpenseBudgetUtilization(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.teBudgetUtilization(),
    queryFn: () => api.getTeamExpenseBudgetUtilization(),
    enabled,
  });
}

export function useTeamExpenseDepartmentBudgetUtilization(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.teDepartmentBudgetUtilization(),
    queryFn: () => api.getTeamExpenseDepartmentBudgetUtilization(),
    enabled,
  });
}

export function useTeamExpenseWorkspaceKpis(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.teWorkspaceKpis(),
    queryFn: () => api.getTeamExpenseWorkspaceKpis(),
    enabled,
  });
}

export function useExpensesWorkspaceKpis(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.expensesWorkspaceKpis(),
    queryFn: () => api.getExpensesWorkspaceKpis(),
    enabled,
  });
}

export function useTeamExpenseExpenseSummary(
  dateFrom?: string,
  dateTo?: string,
  enabled = true
) {
  return useTenantQuery({
    queryKey: queryKeys.teExpenseSummary(dateFrom, dateTo),
    queryFn: () =>
      api.getTeamExpenseExpenseSummary(
        dateFrom || dateTo ? { dateFrom, dateTo } : undefined
      ),
    enabled,
  });
}
