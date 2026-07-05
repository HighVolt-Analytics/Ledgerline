import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useLedgerLink(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ledgerLink(),
    queryFn: () => api.getLedgerLink(),
    enabled,
  });
}
