import { api } from "@/api/client";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useCfoAlerts(period: DashboardPeriod) {
  return useTenantQuery({
    queryKey: queryKeys.cfoAlerts(period),
    queryFn: () => api.getCfoAlerts(period),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
