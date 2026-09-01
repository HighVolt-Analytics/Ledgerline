import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useEfficiencyAutomation() {
  return useTenantQuery({
    queryKey: queryKeys.efficiencyAutomation(),
    queryFn: () => api.getEfficiencyAutomation(),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
