import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useWalletSummary(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.walletSummary(),
    queryFn: () => api.getWalletSummary(),
    enabled,
  });
}
