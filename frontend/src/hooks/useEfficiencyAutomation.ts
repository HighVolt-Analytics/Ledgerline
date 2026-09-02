import { api } from "@/api/client";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useEfficiencyAutomation(period: DashboardPeriod) {
  return useTenantQuery({
    queryKey: queryKeys.efficiencyAutomation(period),
    queryFn: () => api.getEfficiencyAutomation(period),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
