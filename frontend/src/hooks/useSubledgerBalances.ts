import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useApBalances(asOf?: string, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.subledgerApBalances(asOf),
    queryFn: () => api.getApBalances(asOf),
    enabled,
  });
}

export function useArBalances(asOf?: string, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.subledgerArBalances(asOf),
    queryFn: () => api.getArBalances(asOf),
    enabled,
  });
}
