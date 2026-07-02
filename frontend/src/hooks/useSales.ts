import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useSales(enabled = true) {
  return useQuery({
    queryKey: queryKeys.sales(),
    queryFn: () => api.listSales(),
    enabled,
  });
}
