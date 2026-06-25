import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function usePurchases(enabled = true) {
  return useQuery({
    queryKey: queryKeys.purchases(),
    queryFn: () => api.listPurchases(),
    enabled,
  });
}
