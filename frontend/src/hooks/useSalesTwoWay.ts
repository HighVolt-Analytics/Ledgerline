import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useSalesTwoWay(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.salesTwoWay(),
    queryFn: () => api.listSalesTwoWay(),
    enabled,
  });
}
