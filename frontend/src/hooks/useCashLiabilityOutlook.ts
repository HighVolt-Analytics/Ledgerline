import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useCashLiabilityOutlook() {
  return useTenantQuery({
    queryKey: queryKeys.cashLiabilityOutlook(),
    queryFn: () => api.getCashLiabilityOutlook(),
    staleTime: 60_000,
    placeholderData: (previousData) => previousData,
  });
}
