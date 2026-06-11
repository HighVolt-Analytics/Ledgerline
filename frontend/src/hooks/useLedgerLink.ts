import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useLedgerLink(enabled = true) {
  return useQuery({
    queryKey: queryKeys.ledgerLink,
    queryFn: () => api.getLedgerLink(),
    enabled,
  });
}
