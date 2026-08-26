import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { ReportColumnsPanel } from "@/components/reports/ReportColumnsPanel";
import type { ReportCatalogItem, ReportExportFormat, ReportRangeKey } from "@/api/types";
import {
  useReportExportMutation,
  useReportLayouts,
  useReportPreview,
} from "@/hooks/useReportCatalog";
import { useToast } from "@/context/ToastContext";
import { applyColumnLayout } from "@/lib/reportColumnLayout";
import { cn } from "@/lib/cn";

const RANGE_OPTIONS: { value: ReportRangeKey; label: string }[] = [
  { value: "month", label: "This Month" },
  { value: "quarter", label: "This Quarter" },
  { value: "custom", label: "Custom" },
];

type ReportPreviewPanelProps = {
  report: ReportCatalogItem;
  range: ReportRangeKey;
  compare: boolean;
  dateFrom: string;
  dateTo: string;
  onRangeChange: (range: ReportRangeKey) => void;
  onCompareChange: (compare: boolean) => void;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  exportFormat: ReportExportFormat;
};

export function ReportPreviewPanel({
  report,
  range,
  compare,
  dateFrom,
  dateTo,
  onRangeChange,
  onCompareChange,
  onDateFromChange,
  onDateToChange,
  exportFormat,
}: ReportPreviewPanelProps) {
  const { toast } = useToast();
  const preview = useReportPreview(
    report.id,
    range,
    report.supports_compare && compare,
    dateFrom,
    dateTo
  );
  const layouts = useReportLayouts(report.id);
  const exportMutation = useReportExportMutation();
  const customInvalid = range === "custom" && (!dateFrom || !dateTo || dateFrom > dateTo);
  const [selectedLayoutId, setSelectedLayoutId] = useState("");
  const [visibleKeys, setVisibleKeys] = useState<string[]>([]);
  const [defaultApplied, setDefaultApplied] = useState(false);

  useEffect(() => {
    setSelectedLayoutId("");
    setVisibleKeys([]);
    setDefaultApplied(false);
  }, [report.id]);

  useEffect(() => {
    if (defaultApplied || !preview.data || !layouts.isFetched) return;
    const fallback = preview.data.columns;
    const preferred = (layouts.data ?? []).find((row) => row.is_default);
    if (preferred) {
      setSelectedLayoutId(String(preferred.id));
      setVisibleKeys(preferred.column_config.columns);
    } else {
      setVisibleKeys(fallback);
    }
    setDefaultApplied(true);
  }, [defaultApplied, layouts.data, layouts.isFetched, preview.data]);

  const displayed = useMemo(() => {
    if (!preview.data) return null;
    return applyColumnLayout(
      preview.data.columns,
      preview.data.rows,
      visibleKeys.length ? visibleKeys : preview.data.columns
    );
  }, [preview.data, visibleKeys]);

  async function handleExport() {
    if (customInvalid || exportMutation.isPending) return;
    try {
      const layoutId = selectedLayoutId ? Number(selectedLayoutId) : undefined;
      await exportMutation.mutateAsync({
        reportId: report.id,
        body: {
          format: exportFormat,
          range,
          compare: report.supports_compare && compare,
          from: range === "custom" ? dateFrom : undefined,
          to: range === "custom" ? dateTo : undefined,
          layout_id: layoutId,
        },
      });
      toast({ title: `${report.name} exported` });
    } catch (err) {
      toast({
        title: "Export failed",
        description: err instanceof Error ? err.message : "Try again later.",
        variant: "destructive",
      });
    }
  }

  return (
    <Card className="p-4 space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <div role="radiogroup" aria-label="Date range" className="flex flex-wrap gap-2">
            {RANGE_OPTIONS.map((option) => (
              <Button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={range === option.value}
                variant={range === option.value ? "default" : "outline"}
                className="min-h-11"
                data-testid={`range-${report.id}-${option.value}`}
                onClick={() => onRangeChange(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          {range === "custom" ? (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => onDateFromChange(e.target.value)}
                aria-label="From date"
                className="h-11 w-[11rem]"
                data-testid={`preview-from-${report.id}`}
              />
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => onDateToChange(e.target.value)}
                aria-label="To date"
                className="h-11 w-[11rem]"
                data-testid={`preview-to-${report.id}`}
              />
            </div>
          ) : null}
          {report.supports_compare ? (
            <label className="flex items-center gap-2 text-sm min-h-11">
              <Switch
                checked={compare}
                onCheckedChange={onCompareChange}
                data-testid={`compare-${report.id}`}
                aria-label="Compare to prior period"
              />
              Compare to prior period
            </label>
          ) : null}
        </div>
        <div className="flex flex-wrap items-start gap-2">
          {preview.data ? (
            <ReportColumnsPanel
              reportId={report.id}
              catalogColumns={preview.data.columns}
              layouts={layouts.data ?? []}
              visibleKeys={visibleKeys.length ? visibleKeys : preview.data.columns}
              selectedLayoutId={selectedLayoutId}
              onVisibleKeysChange={setVisibleKeys}
              onSelectedLayoutIdChange={setSelectedLayoutId}
            />
          ) : null}
          <Button
            type="button"
            className="min-h-11"
            disabled={customInvalid || exportMutation.isPending || preview.isLoading}
            data-testid={`button-export-${report.id}`}
            onClick={() => void handleExport()}
          >
            {exportMutation.isPending ? "Exporting…" : "Export"}
          </Button>
        </div>
      </div>

      {customInvalid ? (
        <p className="text-sm text-muted-foreground py-6" data-testid={`preview-invalid-range-${report.id}`}>
          From must be on or before To.
        </p>
      ) : null}
      {preview.isLoading || (Boolean(preview.data) && !defaultApplied && !preview.isError) ? (
        <p className="text-sm text-muted-foreground py-6" data-testid={`preview-loading-${report.id}`}>
          Loading report…
        </p>
      ) : null}
      {preview.isError ? (
        <EmptyState
          title="Could not load preview"
          hint={preview.error instanceof Error ? preview.error.message : "Try again later."}
        />
      ) : null}
      {preview.data && !preview.isLoading && !preview.isError && defaultApplied ? (
        <>
          {preview.data.notes ? (
            <p className="text-xs text-muted-foreground" data-testid={`preview-notes-${report.id}`}>
              {preview.data.notes}
            </p>
          ) : null}
          {preview.data.empty ? (
          <EmptyState
            title="No data for this period"
            hint="Processed journals and invoices in this range will appear here."
          />
        ) : (
          <div className="overflow-x-auto">
            <p className="text-xs text-muted-foreground mb-2">
              {preview.data.period_label}
              {preview.data.currency ? ` · ${preview.data.currency}` : ""}
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  {(displayed?.columns ?? preview.data.columns).map((col) => (
                    <th key={col} className="py-1.5 font-medium pr-3">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(displayed?.rows ?? preview.data.rows).map((row, index) => (
                  <tr
                    key={`${report.id}-row-${index}`}
                    className={cn("row-band border-b border-border/60", row.emphasize && "font-semibold")}
                  >
                    {row.cells.map((cell, cellIndex) => (
                      <td
                        key={`${index}-${cellIndex}`}
                        className={cn("py-1.5 pr-3", cellIndex > 0 && "tnum")}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </>
      ) : null}
    </Card>
  );
}
