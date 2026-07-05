import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useWalletSummary(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.walletSummary(),
    queryFn: () => api.getWalletSummary(),
    enabled,
  });
}
