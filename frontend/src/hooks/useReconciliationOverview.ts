import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useReconciliationOverview(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.reconciliationOverview(),
    queryFn: () => api.getReconciliationOverview(),
    enabled,
  });
}

export function useReconciliationDaily(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.reconciliationDaily(),
    queryFn: () => api.listReconciliation(),
    enabled,
  });
}

export function useReconciliationDayDetail(reconDate: string | null, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.reconciliationDayDetail(reconDate ?? ""),
    queryFn: () => api.getReconciliationDayDetail(reconDate!),
    enabled: enabled && Boolean(reconDate),
  });
}
