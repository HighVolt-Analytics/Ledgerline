import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function usePurchasesTwoWay(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.purchasesTwoWay(),
    queryFn: () => api.listPurchasesTwoWay(),
    enabled,
  });
}
