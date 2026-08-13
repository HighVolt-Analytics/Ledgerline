import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useDashboardOverview(month: string, activityLimit = 10) {
  return useTenantQuery({
    queryKey: queryKeys.dashboardOverview(month, activityLimit),
    queryFn: () => api.getDashboardOverview(activityLimit, month),
    enabled: Boolean(month),
    placeholderData: (previousData) => previousData,
  });
}
