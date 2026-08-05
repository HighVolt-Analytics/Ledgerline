import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useTeamExpenseAdvanceSettlement() {
  return useTenantQuery({
    queryKey: queryKeys.teAdvanceSettlement(),
    queryFn: () => api.getTeamExpenseAdvanceSettlement(),
  });
}

export function useTeamExpenseBudgetUtilization() {
  return useTenantQuery({
    queryKey: queryKeys.teBudgetUtilization(),
    queryFn: () => api.getTeamExpenseBudgetUtilization(),
  });
}

export function useTeamExpenseDepartmentBudgetUtilization() {
  return useTenantQuery({
    queryKey: queryKeys.teDepartmentBudgetUtilization(),
    queryFn: () => api.getTeamExpenseDepartmentBudgetUtilization(),
  });
}

export function useTeamExpenseExpenseSummary(dateFrom?: string, dateTo?: string) {
  return useTenantQuery({
    queryKey: queryKeys.teExpenseSummary(dateFrom, dateTo),
    queryFn: () =>
      api.getTeamExpenseExpenseSummary(
        dateFrom || dateTo ? { dateFrom, dateTo } : undefined
      ),
  });
}
