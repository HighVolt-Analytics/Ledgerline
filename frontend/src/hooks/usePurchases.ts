import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function usePurchases(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.purchases(),
    queryFn: () => api.listPurchases(),
    enabled,
  });
}
