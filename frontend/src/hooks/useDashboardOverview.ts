import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useDashboardOverview(month: string, activityLimit = 10) {
  return useQuery({
    queryKey: queryKeys.dashboardOverview(month, activityLimit),
    queryFn: () => api.getDashboardOverview(activityLimit, month),
    enabled: Boolean(month),
  });
}
