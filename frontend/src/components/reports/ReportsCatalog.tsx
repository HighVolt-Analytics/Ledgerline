import { useMemo, useState } from "react";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageTabs } from "@/components/PageTabs";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { ReportCatalogRow } from "@/components/reports/ReportCatalogRow";
import { ReportPreviewPanel } from "@/components/reports/ReportPreviewPanel";
import type { ReportCatalogItem, ReportExportFormat, ReportRangeKey } from "@/api/types";
import {
  REPORT_CATEGORY_LABELS,
  REPORT_CATEGORY_ORDER,
  favouriteItems,
  filterCatalogItems,
  groupCatalogByCategory,
  type ReportCategoryTab,
} from "@/lib/reportCatalog";
import { useReportExportMutation, useReportFavouritesMutation } from "@/hooks/useReportCatalog";
import { useToast } from "@/context/ToastContext";

type ReportsCatalogProps = {
  reports: ReportCatalogItem[];
  favouriteIds: string[];
};

export function ReportsCatalog({ reports, favouriteIds }: ReportsCatalogProps) {
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<ReportCategoryTab>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [range, setRange] = useState<ReportRangeKey>("month");
  const [compare, setCompare] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [exportFormat, setExportFormat] = useState<ReportExportFormat>("xlsx");
  const favMutation = useReportFavouritesMutation();
  const exportMutation = useReportExportMutation();

  const visible = useMemo(
    () => filterCatalogItems(reports, search, tab),
    [reports, search, tab]
  );
  const starred = useMemo(
    () => favouriteItems(filterCatalogItems(reports, search, "all"), favouriteIds),
    [reports, search, favouriteIds]
  );
  const listItems = useMemo(() => {
    const starredIds = new Set(starred.map((item) => item.id));
    return visible.filter((item) => !starredIds.has(item.id));
  }, [visible, starred]);
  const groups = useMemo(() => groupCatalogByCategory(listItems), [listItems]);

  const tabs = [
    { value: "all", label: "All", testid: "tab-reports-all" },
    ...REPORT_CATEGORY_ORDER.map((category) => ({
      value: category,
      label: REPORT_CATEGORY_LABELS[category],
      testid: `tab-reports-${category}`,
    })),
  ];

  function toggleFavourite(reportId: string) {
    const next = favouriteIds.includes(reportId)
      ? favouriteIds.filter((id) => id !== reportId)
      : [...favouriteIds, reportId];
    favMutation.mutate(next, {
      onError: (err) => {
        toast({
          title: "Could not update favourites",
          description: err instanceof Error ? err.message : "Try again later.",
          variant: "destructive",
        });
      },
    });
  }

  async function downloadNow(reportId: string, format: ReportExportFormat) {
    if (range === "custom" && (!dateFrom || !dateTo || dateFrom > dateTo)) {
      toast({
        title: "Choose a valid date range",
        description: "Set From and To before downloading a custom-range report.",
        variant: "destructive",
      });
      return;
    }
    setExportFormat(format);
    try {
      await exportMutation.mutateAsync({
        reportId,
        body: {
          format,
          range,
          compare: Boolean(reports.find((r) => r.id === reportId)?.supports_compare && compare),
          from: range === "custom" ? dateFrom : undefined,
          to: range === "custom" ? dateTo : undefined,
        },
      });
      toast({ title: "Report downloaded" });
    } catch (err) {
      toast({
        title: "Download failed",
        description: err instanceof Error ? err.message : "Try again later.",
        variant: "destructive",
      });
    }
  }

  function renderRow(report: ReportCatalogItem) {
    const expanded = expandedId === report.id;
    return (
      <ReportCatalogRow
        key={report.id}
        report={report}
        favourite={favouriteIds.includes(report.id)}
        expanded={expanded}
        onToggleFavourite={() => toggleFavourite(report.id)}
        onTogglePreview={() => setExpandedId(expanded ? null : report.id)}
        onDownloadFormat={(format) => void downloadNow(report.id, format)}
      >
        {expanded ? (
          <ReportPreviewPanel
            report={report}
            range={range}
            compare={compare}
            dateFrom={dateFrom}
            dateTo={dateTo}
            onRangeChange={setRange}
            onCompareChange={setCompare}
            onDateFromChange={setDateFrom}
            onDateToChange={setDateTo}
            exportFormat={exportFormat}
          />
        ) : null}
      </ReportCatalogRow>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ListSearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search reports"
          testId="input-report-search"
          className="w-full sm:max-w-sm"
        />
      </div>
      <PageTabs
        tabs={tabs}
        value={tab}
        onChange={(value) => setTab(value as ReportCategoryTab)}
        variant="pill"
        data-testid="tabs-report-category"
      />

      {starred.length > 0 ? (
        <Card className="p-4">
          <h2 className="text-sm font-semibold mb-2">Favourites</h2>
          {starred.map(renderRow)}
        </Card>
      ) : null}

      {visible.length === 0 ? (
        <EmptyState
          title="No matching reports"
          hint="Try a different search or category."
        />
      ) : tab === "all" ? (
        groups.map((group) => (
          <Card key={group.category} className="p-4">
            <h2 className="text-sm font-semibold mb-2">{group.label}</h2>
            {group.items.map(renderRow)}
          </Card>
        ))
      ) : listItems.length > 0 ? (
        <Card className="p-4">{listItems.map(renderRow)}</Card>
      ) : null}
    </div>
  );
}
