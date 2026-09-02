import { api } from "@/api/client";
import type { DashboardPeriod } from "@/lib/dashboardPeriod";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useCashLiabilityOutlook(period: DashboardPeriod) {
  return useTenantQuery({
    queryKey: queryKeys.cashLiabilityOutlook(period),
    queryFn: () => api.getCashLiabilityOutlook(period),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
