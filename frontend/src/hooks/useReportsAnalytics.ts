import { useTenantQuery } from "@/hooks/useTenantQuery";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useReportsAnalytics(month: string) {
  return useTenantQuery({
    queryKey: queryKeys.reportsAnalytics(month),
    queryFn: () => api.getReportsAnalytics(month),
    enabled: Boolean(month),
  });
}

export function useReportDocuments(
  filter: { dateFrom?: string; dateTo?: string } | null,
  enabled: boolean
) {
  return useTenantQuery({
    queryKey: queryKeys.reportDocuments(filter?.dateFrom, filter?.dateTo),
    queryFn: () => api.getReportDocuments(filter ?? undefined),
    enabled,
  });
}
