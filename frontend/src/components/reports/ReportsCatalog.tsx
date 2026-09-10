import { useMemo, useState } from "react";
import { ReportCatalogRow } from "@/components/reports/ReportCatalogRow";
import { ReportPreviewPanel } from "@/components/reports/ReportPreviewPanel";
import type { ReportCatalogItem, ReportExportFormat, ReportRangeKey } from "@/api/types";
import {
  REPORT_CATEGORY_ACCENTS,
  REPORT_CATEGORY_LABELS,
  REPORT_CATEGORY_ORDER,
  favouriteItems,
  filterCatalogItems,
  groupCatalogByCategory,
  isFlaggedReport,
  type ReportCategoryTab,
} from "@/lib/reportCatalog";
import { useReportExportMutation, useReportFavouritesMutation } from "@/hooks/useReportCatalog";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/cn";

const SEARCH_SVG = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
    <circle cx="11" cy="11" r="7" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const STAR_FILLED = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" aria-hidden>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26" />
  </svg>
);

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
    () => favouriteItems(reports, favouriteIds),
    [reports, favouriteIds]
  );
  const groups = useMemo(() => {
    const grouped = groupCatalogByCategory(visible);
    if (tab === "all") return grouped;
    return grouped.filter((group) => group.category === tab);
  }, [visible, tab]);
  const flaggedCount = useMemo(
    () => reports.filter(isFlaggedReport).length,
    [reports]
  );
  const categoryCount = useMemo(
    () => groupCatalogByCategory(reports).length,
    [reports]
  );
  const expandedReport = useMemo(
    () => (expandedId ? reports.find((r) => r.id === expandedId) ?? null : null),
    [expandedId, reports]
  );

  const chips: { value: ReportCategoryTab; label: string; testid: string }[] = [
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

  return (
    <div className="reports-catalog">
      <div className="rc-top-bar">
        <h1 className="rc-title">Reports</h1>
        <span className="rc-stats">
          <b>{reports.length}</b> reports &middot; <b>{categoryCount}</b> categories &middot;{" "}
          <b className="flag">{flaggedCount}</b> flagged
        </span>
        <div className="rc-search-wrap">
          {SEARCH_SVG}
          <input
            className="rc-search"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search reports"
            autoComplete="off"
            aria-label="Search reports"
            data-testid="input-report-search"
          />
        </div>
      </div>

      <div className="rc-chips" data-testid="tabs-report-category" role="tablist">
        {chips.map((chip) => {
          const active = tab === chip.value;
          const accent =
            chip.value !== "all" ? REPORT_CATEGORY_ACCENTS[chip.value] : undefined;
          return (
            <button
              key={chip.value}
              type="button"
              role="tab"
              aria-selected={active}
              data-cat={chip.value}
              data-testid={chip.testid}
              className={cn("rc-chip", active && "active")}
              onClick={() => setTab(chip.value)}
            >
              {accent ? (
                <span className="dot" style={{ color: accent }} aria-hidden />
              ) : null}
              {chip.label}
            </button>
          );
        })}
      </div>

      {starred.length > 0 ? (
        <div className="rc-fav-row">
          <span className="rc-fav-label">Favorites:</span>
          <div className="rc-fav-track">
            {starred.map((report) => (
              <div key={report.id} className="rc-fav-chip">
                <span>{STAR_FILLED}</span>
                <span>{report.name}</span>
                <button
                  type="button"
                  className="rm"
                  aria-label={`Remove ${report.name} from favourites`}
                  onClick={() => toggleFavourite(report.id)}
                >
                  &times;
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {visible.length === 0 ? (
        <div className="rc-empty">No reports match your search.</div>
      ) : (
        <div className="rc-grid">
          {groups.map((group) => (
            <section
              key={group.category}
              className="rc-cat-panel"
              data-cat={group.category}
            >
              <div className="rc-cat-head">
                <div className="rc-cat-bar" />
                <h2 className="rc-cat-title">{group.label}</h2>
                <div className="rc-cat-count">{group.items.length}</div>
              </div>
              <div>
                {group.items.map((report) => {
                  const expanded = expandedId === report.id;
                  return (
                    <ReportCatalogRow
                      key={`${group.category}-${report.id}`}
                      report={report}
                      favourite={favouriteIds.includes(report.id)}
                      expanded={expanded}
                      onToggleFavourite={() => toggleFavourite(report.id)}
                      onTogglePreview={() => setExpandedId(expanded ? null : report.id)}
                      onDownloadFormat={(format) => void downloadNow(report.id, format)}
                    />
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}

      {expandedReport ? (
        <div
          id={`report-preview-${expandedReport.id}`}
          role="region"
          aria-label={`${expandedReport.name} preview`}
          className="rc-preview"
        >
          <div className="rc-preview-head">
            <h2 className="rc-preview-title">{expandedReport.name}</h2>
            <button
              type="button"
              className="rc-preview-close"
              onClick={() => setExpandedId(null)}
            >
              Close
            </button>
          </div>
          <ReportPreviewPanel
            report={expandedReport}
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
        </div>
      ) : null}
    </div>
  );
}
