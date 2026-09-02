import { api } from "@/api/client";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useBudgetConcentrationRisk(period: DashboardPeriod) {
  return useTenantQuery({
    queryKey: queryKeys.budgetConcentrationRisk(period),
    queryFn: () => api.getBudgetConcentrationRisk(period),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
