import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  ReportColumnLayoutCreate,
  ReportColumnLayoutUpdate,
  ReportExportRequest,
  ReportRangeKey,
} from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

export function useReportCatalog() {
  return useTenantQuery({
    queryKey: queryKeys.reportCatalog(),
    queryFn: () => api.getReportCatalog(),
  });
}

export function useReportFavouritesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reportIds: string[]) => api.putReportFavourites(reportIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.reportCatalog() });
    },
  });
}

export function useReportPreview(
  reportId: string | null,
  range: ReportRangeKey,
  compare: boolean,
  dateFrom?: string,
  dateTo?: string
) {
  const customReady =
    range !== "custom" || Boolean(dateFrom && dateTo && dateFrom <= dateTo);
  return useTenantQuery({
    queryKey: queryKeys.reportPreview(
      reportId ?? "",
      range,
      compare,
      dateFrom,
      dateTo
    ),
    queryFn: () =>
      api.getReportPreview(reportId as string, {
        range,
        compare,
        from: dateFrom,
        to: dateTo,
      }),
    enabled: Boolean(reportId) && customReady,
  });
}

export function useReportExportMutation() {
  return useMutation({
    mutationFn: ({
      reportId,
      body,
    }: {
      reportId: string;
      body: ReportExportRequest;
    }) => api.exportReport(reportId, body),
  });
}

export function useReportLayouts(reportId: string | null) {
  return useTenantQuery({
    queryKey: queryKeys.reportLayouts(reportId ?? ""),
    queryFn: () => api.listReportLayouts(reportId as string),
    enabled: Boolean(reportId),
  });
}

export function useReportLayoutMutations(reportId: string) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.reportLayouts(reportId) });
  };
  const create = useMutation({
    mutationFn: (body: ReportColumnLayoutCreate) => api.createReportLayout(reportId, body),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({
      layoutId,
      body,
    }: {
      layoutId: number;
      body: ReportColumnLayoutUpdate;
    }) => api.updateReportLayout(reportId, layoutId, body),
    onSuccess: invalidate,
  });
  const setDefault = useMutation({
    mutationFn: (layoutId: number) => api.setDefaultReportLayout(reportId, layoutId),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (layoutId: number) => api.deleteReportLayout(reportId, layoutId),
    onSuccess: invalidate,
  });
  return { create, update, setDefault, remove };
}
