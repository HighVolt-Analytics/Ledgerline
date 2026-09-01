import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function usePositionLiquidity() {
  return useTenantQuery({
    queryKey: queryKeys.positionLiquidity(),
    queryFn: () => api.getPositionLiquidity(),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
