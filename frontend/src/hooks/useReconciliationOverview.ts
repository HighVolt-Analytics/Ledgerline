import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useReconciliationOverview(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.reconciliationOverview(),
    queryFn: () => api.getReconciliationOverview(),
    enabled,
  });
}
