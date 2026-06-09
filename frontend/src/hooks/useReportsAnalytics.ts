import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function useReportsAnalytics(month: string) {
  return useQuery({
    queryKey: queryKeys.reportsAnalytics(month),
    queryFn: () => api.getReportsAnalytics(month),
    enabled: Boolean(month),
  });
}

export function useReportDocuments(
  filter: { dateFrom?: string; dateTo?: string } | null,
  enabled: boolean
) {
  return useQuery({
    queryKey: queryKeys.reportDocuments(filter?.dateFrom, filter?.dateTo),
    queryFn: () => api.getReportDocuments(filter ?? undefined),
    enabled,
  });
}
