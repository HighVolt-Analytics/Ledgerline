import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useApBalances(asOf?: string) {
  return useTenantQuery({
    queryKey: queryKeys.subledgerApBalances(asOf),
    queryFn: () => api.getApBalances(asOf),
  });
}

export function useArBalances(asOf?: string) {
  return useTenantQuery({
    queryKey: queryKeys.subledgerArBalances(asOf),
    queryFn: () => api.getArBalances(asOf),
  });
}
