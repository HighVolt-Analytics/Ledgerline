import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useSales(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.sales(),
    queryFn: () => api.listSales(),
    enabled,
  });
}
