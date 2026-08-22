import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export const LEDGER_EXPORT_PAGE_SIZE = 50;

export function useLedgerLink(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ledgerLinkOverview(),
    queryFn: () => api.getLedgerLink({ fields: "overview" }),
    enabled,
  });
}

export function useLedgerLinkExports(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ledgerLinkExports(),
    queryFn: () => api.getLedgerLinkExports({ limit: LEDGER_EXPORT_PAGE_SIZE }),
    enabled,
  });
}

export function useLedgerLinkDay(day: string | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.ledgerLinkDay(day ?? ""),
    queryFn: () => api.getLedgerLinkDay(day!),
    enabled: enabled && Boolean(day),
  });
}
