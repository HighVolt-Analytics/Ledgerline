import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useWalletSummary(enabled = true) {
  return useQuery({
    queryKey: queryKeys.walletSummary(),
    queryFn: () => api.getWalletSummary(),
    enabled,
  });
}
