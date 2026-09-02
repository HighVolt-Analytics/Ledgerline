import { api } from "@/api/client";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useProcessEfficiencyTrends(period: DashboardPeriod) {
  return useTenantQuery({
    queryKey: queryKeys.processEfficiencyTrends(period),
    queryFn: () => api.getProcessEfficiencyTrends(period),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
