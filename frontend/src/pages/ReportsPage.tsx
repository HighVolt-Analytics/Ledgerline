import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Sector,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { ChartTooltip } from "@/components/ChartTooltip";
import { ExportWorkbookDialog } from "@/components/ExportWorkbookDialog";
import { ReportDownloadMenu } from "@/components/reports/ReportDownloadMenu";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Card } from "@/components/ui/card";
import { useReportDocuments, useReportsAnalytics } from "@/hooks/useReportsAnalytics";
import { axisMoney, currencySymbol, money, toNumber } from "@/lib/format";
import {
  buildMonthsForYear,
  buildReconYears,
  yearFromPeriod,
} from "@/lib/reconciliation";
import { monthToDateRange } from "@/lib/reportExports";
import {
  REPORT_CHART_COLORS,
  defaultReportPeriod,
  mapGlAccountRow,
  mapVendorSpendRow,
} from "@/lib/reportsData";

const CHART_MARGIN = { top: 4, right: 12, left: 8, bottom: 0 };
const PIE_HOVER_OFFSET = 6;

type PieSectorProps = {
  cx?: number;
  cy?: number;
  innerRadius?: number;
  outerRadius?: number;
  startAngle?: number;
  endAngle?: number;
  fill?: string;
};

function renderActivePieSector(props: PieSectorProps) {
  const { cx = 0, cy = 0, innerRadius = 0, outerRadius = 0, startAngle, endAngle, fill } = props;
  return (
    <Sector
      cx={cx}
      cy={cy}
      innerRadius={innerRadius}
      outerRadius={outerRadius + PIE_HOVER_OFFSET}
      startAngle={startAngle}
      endAngle={endAngle}
      fill={fill}
      stroke="hsl(var(--background))"
      strokeWidth={2}
    />
  );
}

function firstDayOfMonthIso(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function pctDelta(pct: number | null | undefined, goodWhenDown = false) {
  if (pct == null || Number.isNaN(pct)) return undefined;
  const dir = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  const text = `${pct > 0 ? "+" : ""}${pct.toFixed(0)}%`;
  const good = goodWhenDown ? pct < 0 : pct > 0;
  return { dir, text, good } as const;
}

function countDelta(delta: number | null | undefined) {
  if (delta == null) return undefined;
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return {
    dir,
    text: `${delta > 0 ? "+" : ""}${delta} vs prior month`,
    good: delta >= 0,
  } as const;
}

export function ReportsPage() {
  const [month, setMonth] = useState(() => defaultReportPeriod());
  const [toast, setToast] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportMode, setExportMode] = useState<"range" | "all">("range");
  const [dateFrom, setDateFrom] = useState(firstDayOfMonthIso);
  const [dateTo, setDateTo] = useState(todayIso);
  const [exportBusy, setExportBusy] = useState(false);
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
  const [activePieIndex, setActivePieIndex] = useState<number | null>(null);

  const { data: analytics, isLoading, error } = useReportsAnalytics(month);
  const rangeInvalid = exportMode === "range" && dateFrom > dateTo;

  const yearOptions = useMemo(() => buildReconYears(null), []);
  const selectedYear = month ? yearFromPeriod(month) : yearOptions[0] ?? "";
  const monthOptions = useMemo(
    () => (selectedYear ? buildMonthsForYear(selectedYear) : []),
    [selectedYear]
  );

  const handleYearChange = (year: string) => {
    const months = buildMonthsForYear(year);
    if (months.length === 0) {
      setMonth("");
      return;
    }
    const monthPart = month.slice(5, 7);
    const keepMonth = months.find((m) => m.value.endsWith(`-${monthPart}`));
    setMonth((keepMonth ?? months[0]).value);
  };

  const handleMonthChange = (monthKey: string) => {
    setMonth(monthKey);
  };

  const exportFilter = useMemo(() => {
    if (!exportOpen || rangeInvalid) return null;
    if (exportMode === "all") return {};
    return { dateFrom, dateTo };
  }, [exportOpen, exportMode, dateFrom, dateTo, rangeInvalid]);

  const { data: exportDocs } = useReportDocuments(exportFilter, Boolean(exportFilter));
  const { data: allDocs } = useReportDocuments({}, exportOpen && exportMode === "all");

  const currency = analytics?.base_currency ?? "AUD";
  const taxLabel = analytics?.tax_label ?? "GST";
  const symbol = currencySymbol(currency);
  const fmt = (v: number) => money(v, currency);

  const byAccount = useMemo(
    () => (analytics?.by_gl_account ?? []).map(mapGlAccountRow),
    [analytics?.by_gl_account]
  );
  const vendors = useMemo(
    () => (analytics?.top_vendors ?? []).map(mapVendorSpendRow),
    [analytics?.top_vendors]
  );

  const netSpend = toNumber(analytics?.net_spend);
  const taxTotal = toNumber(analytics?.tax_total);
  const grossSpend = toNumber(analytics?.gross_spend);
  const documentCount = analytics?.document_count ?? 0;
  const trends = analytics?.kpi_trends;

  const exportCount = exportDocs?.length ?? 0;
  const totalDocuments = exportMode === "all" ? (allDocs?.length ?? exportCount) : exportCount;

  async function exportWorkbook() {
    if (rangeInvalid || exportBusy) return;

    setExportBusy(true);
    try {
      const filter = exportMode === "all" ? undefined : { dateFrom, dateTo };
      const { filename } = await api.generateReport(filter);
      await api.downloadReport(filter, filename);
      setToast("Workbook downloaded.");
      setExportOpen(false);
      window.setTimeout(() => setToast(null), 3500);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Workbook export failed.");
      window.setTimeout(() => setToast(null), 3500);
    } finally {
      setExportBusy(false);
    }
  }

  const periodSelector = (
    <YearMonthPeriodPicker
      year={selectedYear}
      monthKey={month}
      yearOptions={yearOptions}
      monthOptions={monthOptions}
      onYearChange={handleYearChange}
      onMonthChange={handleMonthChange}
      disabled={isLoading}
      yearId="report-year"
      monthId="report-month"
      yearTestId="select-report-year"
      monthTestId="select-report-month"
      pickerTestId="report-period-picker"
    />
  );

  const headerActions = (
    <ReportDownloadMenu
      month={month}
      analytics={analytics}
      periodSelector={periodSelector}
      disabled={isLoading}
      onCustomWorkbook={() => {
        const range = monthToDateRange(month);
        setDateFrom(range.dateFrom);
        setDateTo(range.dateTo);
        setExportMode("range");
        setExportOpen(true);
      }}
      onToast={setToast}
    />
  );

  if (isLoading) {
    return (
      <div>
        <PageHeader
          title="Reports"
          subtitle="Spend analytics, GL distribution and tax summary."
        />
        <PageLoader />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader
          title="Reports"
          subtitle="Spend analytics, GL distribution and tax summary."
        />
        <EmptyState
          title="Could not load reports"
          hint={error instanceof Error ? error.message : "Try again later."}
        />
      </div>
    );
  }

  if (!analytics?.period_has_data) {
    return (
      <div>
        <PageHeader
          title="Reports"
          subtitle="Spend analytics, GL distribution and tax summary."
          actions={headerActions}
        />
        <EmptyState
          title="No processed invoices for this period"
          hint="Reports include processed invoices only. Process documents in Inbox or Approvals, then return here."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Reports"
        subtitle="Spend analytics, GL distribution and tax summary."
        actions={headerActions}
      />

      {toast && (
        <Card className="p-3 mb-4 text-sm border-primary/30 bg-primary/5">{toast}</Card>
      )}

      {exportOpen && (
        <ExportWorkbookDialog
          open={exportOpen}
          onClose={() => setExportOpen(false)}
          exportMode={exportMode}
          onExportModeChange={setExportMode}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          exportCount={exportCount}
          totalDocuments={totalDocuments}
          rangeInvalid={rangeInvalid}
          busy={exportBusy}
          onExport={() => void exportWorkbook()}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <KpiCard
          label="Net spend (ex-tax)"
          value={fmt(netSpend)}
          delta={pctDelta(trends?.net_spend_delta_pct)}
          testid="kpi-net"
        />
        <KpiCard
          label={`${taxLabel} reclaimable`}
          value={fmt(taxTotal)}
          delta={pctDelta(trends?.tax_delta_pct)}
          testid="kpi-tax"
        />
        <KpiCard
          label="Gross spend"
          value={fmt(grossSpend)}
          delta={pctDelta(trends?.gross_spend_delta_pct)}
          testid="kpi-gross"
        />
        <KpiCard
          label="Documents"
          value={documentCount}
          delta={countDelta(trends?.documents_delta)}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">Spend by GL account</h3>
          <div className="h-64">
            {byAccount.length === 0 ? (
              <p className="text-sm text-muted-foreground h-full flex items-center justify-center">
                No GL accounts mapped for this period.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byAccount} layout="vertical" margin={CHART_MARGIN}>
                  <XAxis
                    type="number"
                    tick={{ fontSize: 10 }}
                    stroke="hsl(var(--muted-foreground))"
                    tickFormatter={(v) => axisMoney(Number(v), symbol)}
                  />
                  <YAxis
                    type="category"
                    dataKey="account"
                    width={120}
                    tick={{ fontSize: 9 }}
                    stroke="hsl(var(--muted-foreground))"
                  />
                  <Tooltip
                    cursor={{ fill: "hsl(var(--muted) / 0.45)" }}
                    content={({ active, payload, label }) => (
                      <ChartTooltip
                        active={active}
                        payload={payload}
                        label={label}
                        valueFormatter={(v) => fmt(v)}
                      />
                    )}
                  />
                  <Bar
                    dataKey="amount"
                    radius={[0, 4, 4, 0]}
                    isAnimationActive
                    animationDuration={500}
                    animationEasing="ease-out"
                    onMouseLeave={() => setHoveredBar(null)}
                    activeBar={{
                      stroke: "hsl(var(--foreground) / 0.12)",
                      strokeWidth: 1,
                    }}
                  >
                    {byAccount.map((row, index) => (
                      <Cell
                        key={row.account}
                        fill={REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length]}
                        opacity={hoveredBar === null || hoveredBar === index ? 1 : 0.5}
                        onMouseEnter={() => setHoveredBar(index)}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">Account distribution</h3>
          <div className="h-64">
            {byAccount.length === 0 ? (
              <p className="text-sm text-muted-foreground h-full flex items-center justify-center">
                No account distribution for this period.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={byAccount}
                    dataKey="amount"
                    nameKey="account"
                    cx="50%"
                    cy="50%"
                    outerRadius={85}
                    innerRadius={45}
                    isAnimationActive
                    animationDuration={500}
                    animationEasing="ease-out"
                    activeIndex={activePieIndex ?? undefined}
                    activeShape={renderActivePieSector}
                    onMouseEnter={(_, index) => setActivePieIndex(index)}
                    onMouseLeave={() => setActivePieIndex(null)}
                  >
                    {byAccount.map((row, index) => (
                      <Cell
                        key={row.account}
                        fill={REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length]}
                        opacity={activePieIndex === null || activePieIndex === index ? 1 : 0.5}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    content={({ active, payload, label }) => (
                      <ChartTooltip
                        active={active}
                        payload={payload}
                        label={label}
                        valueFormatter={(v) => fmt(v)}
                      />
                    )}
                  />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">GL account detail</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 font-medium">Account</th>
                <th className="py-1.5 font-medium text-right">Lines</th>
                <th className="py-1.5 font-medium text-right">Net</th>
              </tr>
            </thead>
            <tbody>
              {byAccount.map((row) => (
                <tr key={row.account} className="row-band border-b border-border/60">
                  <td className="py-1.5">{row.account}</td>
                  <td className="py-1.5 text-right tnum">{row.count}</td>
                  <td className="py-1.5 text-right tnum font-medium">{fmt(row.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">Top vendors</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="py-1.5 font-medium">Vendor</th>
                <th className="py-1.5 font-medium text-right">Docs</th>
                <th className="py-1.5 font-medium text-right">Spend</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((row) => (
                <tr key={row.vendor} className="row-band border-b border-border/60">
                  <td className="py-1.5 truncate max-w-[180px]">{row.vendor}</td>
                  <td className="py-1.5 text-right tnum">{row.count}</td>
                  <td className="py-1.5 text-right tnum font-medium">{fmt(row.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
