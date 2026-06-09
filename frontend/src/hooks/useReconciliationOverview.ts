import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useReconciliationOverview(enabled = true) {
  return useQuery({
    queryKey: queryKeys.reconciliationOverview,
    queryFn: () => api.getReconciliationOverview(),
    enabled,
  });
}
