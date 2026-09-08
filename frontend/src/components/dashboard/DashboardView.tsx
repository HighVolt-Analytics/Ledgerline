import { Fragment, useEffect, useMemo, useState, type ReactElement, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import { Skeleton } from "@/components/skeleton/Skeleton";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { usePositionLiquidity } from "@/hooks/usePositionLiquidity";
import { useEfficiencyAutomation } from "@/hooks/useEfficiencyAutomation";
import { useCashLiabilityOutlook } from "@/hooks/useCashLiabilityOutlook";
import { useBudgetConcentrationRisk } from "@/hooks/useBudgetConcentrationRisk";
import { useCfoAlerts } from "@/hooks/useCfoAlerts";
import { useProcessEfficiencyTrends } from "@/hooks/useProcessEfficiencyTrends";
import {
  DASHBOARD_PERIOD_OPTIONS,
  type DashboardPeriod,
} from "@/lib/dashboardPeriod";
import type {
  ApAgeingBucket,
  BudgetDepartmentRow,
  CashOutlookWeek,
  CfoAlertRow,
  ProcessEfficiencyTrendPoint,
  VendorConcentrationRow,
} from "@/api/types";
import {
  cfoAxisCompact,
  cfoCompact,
  cfoMoney,
  cfoN0,
  cfoN1,
  cfoPct,
} from "@/lib/cfoFormat";
import {
  KPI_MODULE_CHART_DARK,
  KPI_MODULE_CHART_LIGHT,
} from "@/lib/kpiModuleColors";
import { useTheme } from "@/context/ThemeContext";

const CHART_AXIS = "hsl(var(--muted-foreground))";
const CHART_GRID = "hsl(var(--border))";
const CHART_INK = "hsl(var(--foreground))";

const CHART_HEIGHT = {
  cash: 400,
  ageing: 260,
  tall: 320,
} as const;

const CHART_MARGIN = {
  default: { top: 4, right: 8, left: 0, bottom: 0 },
  cash: { top: 4, right: 4, left: 0, bottom: 0 },
  budget: { top: 8, right: 52, left: 4, bottom: 4 },
  budgetHorizontal: { top: 8, right: 56, left: 0, bottom: 4 },
  pareto: { top: 4, right: 8, left: 0, bottom: 4 },
  trend: { top: 4, right: 8, left: 0, bottom: 0 },
  ageing: { top: 0, right: 12, left: 0, bottom: 0 },
} as const;

const BUDGET_STACK_MIN_SHARE = 0.018;

type BudgetStackColors = {
  budgetTrack: string;
  budgetTrackStroke: string;
  segmentStroke: string;
  actual: string;
  actualOver: string;
  committed: string;
  labelFill: string;
};

function budgetStackColors(dark: boolean): BudgetStackColors {
  const palette = dark ? KPI_MODULE_CHART_DARK : KPI_MODULE_CHART_LIGHT;
  return {
    // Raised neutral track — muted-foreground at low alpha vanishes on dark cards.
    budgetTrack: dark ? "hsl(214 14% 38%)" : "hsl(var(--muted-foreground) / 0.12)",
    budgetTrackStroke: dark ? "hsl(214 12% 50%)" : "hsl(var(--border))",
    segmentStroke: dark ? "hsl(var(--card))" : "hsl(var(--card))",
    actual: palette.blue,
    actualOver: palette.rose,
    committed: dark ? palette.teal : palette.sage,
    labelFill: dark ? "hsl(var(--foreground) / 0.72)" : "hsl(var(--muted-foreground))",
  };
}

/** Boost tiny non-zero segments so they remain visible inside the budget bar. */
function budgetStackSegments(actual: number, committed: number, budget: number) {
  const headroom = Math.max(0, budget - actual - committed);
  if (budget <= 0) {
    return { chartActual: actual, chartCommitted: committed, headroom: 0 };
  }

  let chartActual = actual;
  let chartCommitted = committed;
  let chartHeadroom = headroom;
  const minVal = budget * BUDGET_STACK_MIN_SHARE;
  let boost = 0;
  if (chartActual > 0 && chartActual < minVal) boost += minVal - chartActual;
  if (chartCommitted > 0 && chartCommitted < minVal) boost += minVal - chartCommitted;
  if (boost > 0 && chartHeadroom >= boost) {
    if (chartActual > 0 && chartActual < minVal) chartActual = minVal;
    if (chartCommitted > 0 && chartCommitted < minVal) chartCommitted = minVal;
    chartHeadroom = Math.max(0, budget - chartActual - chartCommitted);
  }

  // Reserve a hairline slice so utilisation labels can anchor on the bar end.
  if (chartHeadroom === 0 && budget > 0 && (actual > 0 || committed > 0)) {
    const labelSlice = budget * 0.0015;
    chartHeadroom = labelSlice;
    if (chartCommitted >= labelSlice) chartCommitted -= labelSlice;
    else if (chartActual >= labelSlice) chartActual -= labelSlice;
  }

  return { chartActual, chartCommitted, headroom: chartHeadroom };
}

const AGEING_COLORS = [
  KPI_MODULE_CHART_LIGHT.blue,
  KPI_MODULE_CHART_LIGHT.violet,
  "hsl(var(--warning))",
  KPI_MODULE_CHART_LIGHT.rust,
  "hsl(var(--destructive))",
] as const;

type LegendItem = { color: string; label: string; line?: boolean; dashed?: boolean };

function cfoBudgetAxisLabel(name: string, maxLen = 20) {
  const tick = name.includes(" & ") ? name.replace(" & ", " &\n") : name;
  const primary = tick.split("\n")[0] ?? tick;
  if (primary.length <= maxLen) return tick;
  return `${primary.slice(0, maxLen - 1)}…`;
}

type BudgetChartRow = {
  name: string;
  fullName: string;
  budget: number;
  actual: number;
  committed: number;
  remaining: number;
  utilisedPct: number;
  over: boolean;
  chartActual: number;
  chartCommitted: number;
  headroom: number;
};

function BudgetChartTooltip({
  active,
  row,
}: {
  active?: boolean;
  row?: BudgetChartRow;
}) {
  if (!active || !row) return null;
  const remaining = row.budget - row.actual - row.committed;
  const rows = [
    { label: "Budget", value: cfoN0(row.budget), valueClass: "text-foreground" },
    {
      label: "Actual",
      value: cfoN0(row.actual),
      valueClass: row.over ? "text-destructive" : "text-foreground",
    },
    { label: "Committed", value: cfoN0(row.committed), valueClass: "text-foreground" },
    {
      label: "Remaining",
      value: cfoN0(remaining),
      valueClass: remaining < 0 ? "text-destructive" : "text-foreground",
    },
  ] as const;

  return (
    <div className="chart-tooltip cfo-budget-chart-tooltip">
      <p className="chart-tooltip-label">{row.fullName}</p>
      <dl className="cfo-budget-chart-tooltip-grid">
        {rows.map((item) => (
          <Fragment key={item.label}>
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className={cn("tnum font-medium", item.valueClass)}>{item.value}</dd>
          </Fragment>
        ))}
      </dl>
      <p className="chart-tooltip-value tnum mt-2 mb-0 text-[hsl(var(--nav-accent))]">
        {cfoPct(row.utilisedPct)} utilised
        {row.over ? " · over budget" : ""}
      </p>
      <p className="text-[11px] text-muted-foreground mt-1.5 mb-0">
        Committed = in-flight team expense claims
      </p>
    </div>
  );
}

function CfoChartLegend({ items }: { items: LegendItem[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 px-4 pt-3 pb-2 text-[11px] text-muted-foreground">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5 whitespace-nowrap">
          {item.line ? (
            <span
              className="inline-block w-3.5 h-0 shrink-0 border-t-[1.5px]"
              style={{
                borderColor: item.color,
                borderStyle: item.dashed ? "dashed" : "solid",
              }}
            />
          ) : (
            <span
              className="inline-block w-2 h-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: item.color }}
            />
          )}
          {item.label}
        </span>
      ))}
    </div>
  );
}

function CfoChartShell({
  height,
  fill,
  children,
  className,
}: {
  height: number;
  fill?: boolean;
  children: ReactElement;
  className?: string;
}) {
  if (fill) {
    return (
      <div className={cn("cfo-split-panel__chart-fill overflow-visible", className)}>
        <ResponsiveContainer width="100%" height="100%" minWidth={200}>
          {children}
        </ResponsiveContainer>
      </div>
    );
  }

  return (
    <div className={cn("w-full overflow-visible", className)} style={{ height, minHeight: height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={200} minHeight={height}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}

function CfoChartBlock({
  height,
  fill,
  legend,
  children,
  className,
}: {
  height: number;
  fill?: boolean;
  legend?: LegendItem[];
  children: ReactElement;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", fill && "flex flex-1 flex-col min-h-0", className)}>
      {legend ? <CfoChartLegend items={legend} /> : null}
      <CfoChartShell height={height} fill={fill} className={legend ? "px-1" : undefined}>
        {children}
      </CfoChartShell>
    </div>
  );
}

const CASH_STACK = [
  {
    key: "confirmed",
    apiField: "confirmed_ap",
    label: "Scheduled payments",
    color: KPI_MODULE_CHART_LIGHT.blue,
  },
  {
    key: "probable",
    apiField: "probable_ap",
    label: "Due-date AP",
    color: KPI_MODULE_CHART_LIGHT.violet,
  },
  {
    key: "recurring",
    apiField: "recurring",
    label: "Recurring vendors",
    color: KPI_MODULE_CHART_LIGHT.teal,
  },
  {
    key: "reimbursements",
    apiField: "reimbursements",
    label: "Expense reimbursements",
    color: KPI_MODULE_CHART_LIGHT.sage,
  },
  {
    key: "advances",
    apiField: "advances",
    label: "Employee advances",
    color: KPI_MODULE_CHART_LIGHT.rust,
  },
  {
    key: "tax",
    apiField: "tax",
    label: "Tax / BAS",
    color: KPI_MODULE_CHART_LIGHT.rose,
  },
] as const;

function SectionHead({
  title,
  hint,
  demo,
}: {
  title: string;
  hint?: string;
  demo?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-3 mt-8 mb-3 first:mt-0">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground m-0">
        {title}
      </h2>
      {demo ? (
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground border border-dashed border-border rounded px-1.5 py-0.5">
          Demo data
        </span>
      ) : null}
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

function PanelCard({
  title,
  meta,
  children,
  foot,
  aside,
  flushBody,
  stretchBody,
  className,
}: {
  title: string;
  meta?: string;
  children: ReactNode;
  foot?: ReactNode;
  aside?: ReactNode;
  flushBody?: boolean;
  stretchBody?: boolean;
  className?: string;
}) {
  return (
    <Card className={cn("dash-card--elevated overflow-hidden flex flex-col", className)}>
      <div className="flex flex-wrap items-baseline gap-2 border-b border-border/60 px-4 py-3 shrink-0">
        <h3 className="text-sm font-semibold m-0">{title}</h3>
        {meta ? <span className="text-xs text-muted-foreground ml-auto text-right max-w-[55%]">{meta}</span> : null}
      </div>
      <div
        className={cn(
          flushBody ? "min-w-0" : "p-4 min-w-0",
          stretchBody && "flex flex-1 flex-col min-h-0"
        )}
      >
        {children}
      </div>
      {aside ? <div className="min-w-0 shrink-0 mt-auto">{aside}</div> : null}
      {foot ? (
        <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 border-t border-border/60 px-4 py-2.5 text-[11px] text-muted-foreground shrink-0">
          {foot}
        </div>
      ) : null}
    </Card>
  );
}

type KpiTileDef = {
  label: string;
  value: ReactNode;
  foot?: ReactNode;
  meter?: { pct: number; tone?: "pos" | "warn" | "neg" };
};

function CfoKpiTile({ label, value, foot, meter }: KpiTileDef) {
  const meterClass =
    meter?.tone === "neg"
      ? "kpi-card__meter-fill--neg"
      : meter?.tone === "warn"
        ? "kpi-card__meter-fill--warn"
        : meter?.tone === "pos"
          ? "kpi-card__meter-fill--pos"
          : "kpi-card__meter-fill--warn";
  const meterWidth = meter ? kpiMeterWidth(meter.pct) : 0;

  return (
    <Card className="kpi-card kpi-card--elevated p-4 min-w-0">
      <p className="kpi-card__label">{label}</p>
      <p className="kpi-card__value tnum">{value}</p>
      {foot ? <div className="kpi-card__foot">{foot}</div> : null}
      {meter ? (
        <div className="kpi-card__meter-wrap">
          <div
            className="kpi-card__meter"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(meterWidth)}
          >
            <div
              className={cn("kpi-card__meter-fill", meterClass)}
              data-has-value={meterWidth > 0 ? "true" : "false"}
              style={{ width: `${meterWidth}%` }}
            />
          </div>
        </div>
      ) : null}
    </Card>
  );
}

const PRIMARY_KPI_TILE_COUNT = 10;
const SECONDARY_KPI_TILE_COUNT = 10;

function CfoKpiGridSkeleton({ count }: { count: number }) {
  return (
    <div className="kpi-card-grid" aria-busy="true" aria-label="Loading KPIs">
      {Array.from({ length: count }, (_, i) => (
        <Card key={i} className="kpi-card kpi-card--elevated p-4 min-w-0 space-y-2.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-20" />
          <Skeleton className="h-3 w-32" />
        </Card>
      ))}
    </div>
  );
}

function CfoKpiLoadError({ message }: { message: string }) {
  return (
    <Card className="dash-card--elevated p-4 text-sm text-destructive" role="alert">
      {message}
    </Card>
  );
}

function CfoChartPanelSkeleton({ height, fill }: { height: number; fill?: boolean }) {
  return (
    <div
      className={cn("px-4 py-4", fill && "flex flex-1 flex-col min-h-0")}
      aria-busy="true"
      aria-label="Loading chart"
    >
      <Skeleton className="h-4 w-48 mb-4 shrink-0" />
      <Skeleton
        style={fill ? undefined : { height, minHeight: height }}
        className={cn("w-full rounded-md", fill && "flex-1 min-h-[260px]")}
      />
    </div>
  );
}

function parseApiAmount(value: string | null | undefined): number {
  if (value == null || value === "") return 0;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function kpiMeterWidth(pct: number): number {
  if (!Number.isFinite(pct)) return 0;
  return Math.min(100, Math.max(0, pct));
}

function derivePct(part: number, whole: number): number | null {
  if (whole <= 0) return null;
  return kpiMeterWidth((part / whole) * 100);
}

function PrimaryKpis({ period }: { period: DashboardPeriod }) {
  const { data, isLoading, isError, error } = usePositionLiquidity(period);

  if (isLoading && !data) {
    return <CfoKpiGridSkeleton count={PRIMARY_KPI_TILE_COUNT} />;
  }
  if (isError || !data?.kpis) {
    return (
      <CfoKpiLoadError
        message={
          error?.message
            ? `Could not load position & liquidity figures. ${error.message}`
            : "Could not load position & liquidity figures."
        }
      />
    );
  }

  const k = data.kpis;
  const K = {
    apOutstanding: parseApiAmount(k.ap_outstanding),
    approvedNotPaid: parseApiAmount(k.approved_not_paid),
    due7: parseApiAmount(k.due_next_7_days),
    due14: parseApiAmount(k.due_next_14_days),
    due30: parseApiAmount(k.due_next_30_days),
    overdue: parseApiAmount(k.overdue),
    overduePct: k.overdue_pct != null ? parseApiAmount(k.overdue_pct) : null,
    overdueThreshold: parseApiAmount(k.overdue_threshold_pct) || 10,
    utilisation:
      k.budget_utilisation_pct != null ? parseApiAmount(k.budget_utilisation_pct) : null,
    actualYTD: parseApiAmount(k.budget_actual),
    budgetYTD: parseApiAmount(k.budget_allocated),
    budgetCommitted: parseApiAmount(k.budget_committed),
    advancesOutstanding: parseApiAmount(k.advances_outstanding),
    advancesOverdue: parseApiAmount(k.advances_overdue),
    advancesOverdueEmployees: k.advances_overdue_employees,
    openExceptions: k.open_exceptions_count,
    exceptionAtRisk: parseApiAmount(k.open_exceptions_at_risk),
    claimsPending: k.claims_pending_count,
    claimsPendingValue: parseApiAmount(k.claims_pending_value),
    toReviewCount: k.documents_to_review_count,
    toReviewValue: parseApiAmount(k.documents_to_review_value),
    processingCount: k.documents_processing_count,
    processingValue: parseApiAmount(k.documents_processing_value),
    paymentsQueueCount: k.payments_queue_count,
    paymentsQueueValue: parseApiAmount(k.payments_queue_value),
  };

  const pipelineCount = K.toReviewCount + K.processingCount;
  const pipelineValue = K.toReviewValue + K.processingValue;

  const currency = data.meta.currency ?? "AUD";
  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">{currency === "AUD" ? "A$" : `${currency} `}</span>
      {cfoN0(v)}
    </>
  );

  const overduePct =
    K.overduePct ?? derivePct(K.overdue, K.apOutstanding);
  const utilisation =
    K.utilisation ?? derivePct(K.actualYTD, K.budgetYTD);
  const overdueMeterPct =
    overduePct != null && K.overdueThreshold > 0
      ? kpiMeterWidth((overduePct / K.overdueThreshold) * 100)
      : null;

  const tiles: KpiTileDef[] = [
    {
      label: "AP outstanding",
      value: cur(K.apOutstanding),
      foot: (
        <>
          Netted ledger balance · Aged Payables report
        </>
      ),
    },
    {
      label: "Due next 7 days",
      value: cur(K.due7),
      foot: (
        <>
          14 d <span className="tnum">{cfoN0(K.due14)}</span> · 30 d{" "}
          <span className="tnum">{cfoN0(K.due30)}</span>
        </>
      ),
    },
    {
      label: "Overdue",
      value: cur(K.overdue),
      foot:
        overduePct != null ? (
          <>
            <span className="text-destructive font-medium tnum">{cfoPct(overduePct)}</span> of AP ·
            threshold {cfoPct(K.overdueThreshold)}
          </>
        ) : (
          <>Threshold {cfoPct(K.overdueThreshold)}</>
        ),
      meter:
        overdueMeterPct != null
          ? { pct: overdueMeterPct, tone: "neg" }
          : undefined,
    },
    {
      label: "Approved · awaiting payment",
      value: cur(K.approvedNotPaid),
      foot: (
        <>
          AP outstanding <span className="tnum">{cfoN0(K.apOutstanding)}</span> · ready for Payments
        </>
      ),
    },
    {
      label: "Documents in pipeline",
      value: (
        <>
          {cfoN0(pipelineCount)}
          <span className="text-base font-medium text-muted-foreground ml-1">docs</span>
        </>
      ),
      foot: (
        <>
          To Review <span className="tnum">{cfoN0(K.toReviewCount)}</span> · Processing{" "}
          <span className="tnum">{cfoN0(K.processingCount)}</span>
          {pipelineValue > 0 ? (
            <>
              {" "}
              · <span className="tnum">{cfoN0(pipelineValue)}</span> value
            </>
          ) : null}
        </>
      ),
    },
    {
      label: "Payments queue",
      value: (
        <>
          {cfoN0(K.paymentsQueueCount)}
          <span className="text-base font-medium text-muted-foreground ml-1">payments</span>
        </>
      ),
      foot: (
        <>
          <span className="tnum">{cfoN0(K.paymentsQueueValue)}</span> queued for release
        </>
      ),
    },
    {
      label: "Budget utilisation",
      value: utilisation != null ? cfoPct(utilisation) : "—",
      foot: (
        <>
          Actual <span className="tnum">{cfoCompact(K.actualYTD)}</span> of{" "}
          <span className="tnum">{cfoCompact(K.budgetYTD)}</span>
          {K.budgetCommitted > 0 ? (
            <>
              {" "}
              · committed <span className="tnum">{cfoCompact(K.budgetCommitted)}</span>
            </>
          ) : null}
        </>
      ),
      meter: utilisation != null ? { pct: kpiMeterWidth(utilisation), tone: "warn" } : undefined,
    },
    {
      label: "Open exceptions",
      value: (
        <>
          {cfoN0(K.openExceptions)}
          <span className="text-base font-medium text-muted-foreground ml-1">flags</span>
        </>
      ),
      foot: (
        <>
          Control Centre · <span className="tnum">{cfoN0(K.exceptionAtRisk)}</span> at risk
        </>
      ),
    },
    {
      label: "Expense claims pending",
      value: (
        <>
          {cfoN0(K.claimsPending)}
          <span className="text-base font-medium text-muted-foreground ml-1">claims</span>
        </>
      ),
      foot: (
        <>
          Team expenses · <span className="tnum">{cfoN0(K.claimsPendingValue)}</span> awaiting sign-off
        </>
      ),
    },
    {
      label: "Employee advances",
      value: cur(K.advancesOutstanding),
      foot: (
        <>
          <span className="text-destructive font-medium tnum">{cfoN0(K.advancesOverdue)}</span>{" "}
          overdue · {K.advancesOverdueEmployees} employees
        </>
      ),
    },
  ];

  return (
    <div className="kpi-card-grid">
      {tiles.map((t) => (
        <CfoKpiTile key={t.label} {...t} />
      ))}
    </div>
  );
}

function SecondaryKpis({ period }: { period: DashboardPeriod }) {
  const { data, isLoading, isError, error } = useEfficiencyAutomation(period);

  if (isLoading && !data) {
    return <CfoKpiGridSkeleton count={SECONDARY_KPI_TILE_COUNT} />;
  }
  if (isError || !data?.kpis) {
    return (
      <CfoKpiLoadError
        message={
          error?.message
            ? `Could not load efficiency & automation figures. ${error.message}`
            : "Could not load efficiency & automation figures."
        }
      />
    );
  }

  const k = data.kpis;
  const currency = data.meta.currency ?? "AUD";
  const moneyPrefix = currency === "AUD" ? "A$" : `${currency} `;

  const K = {
    touchless:
      k.touchless_processing_pct != null ? parseApiAmount(k.touchless_processing_pct) : null,
    touchlessTarget: parseApiAmount(k.touchless_target_pct) || 85,
    firstPass:
      k.first_pass_validation_pct != null ? parseApiAmount(k.first_pass_validation_pct) : null,
    avgProcMins: k.avg_processing_minutes != null ? parseApiAmount(k.avg_processing_minutes) : null,
    baselineMins: parseApiAmount(k.manual_processing_minutes_baseline) || 182,
    hoursSaved: parseApiAmount(k.hours_saved_ytd),
    fte: k.fte_equivalent != null ? parseApiAmount(k.fte_equivalent) : null,
    invoicesYTD: k.documents_processed_ytd,
    invoicesMTD: k.documents_processed_mtd,
    captureEmail: k.documents_capture_email,
    captureUpload: k.documents_capture_upload,
    captureWhatsapp: k.documents_capture_whatsapp,
    captureViber: k.documents_capture_viber,
    vaultDocs: k.vault_documents_total,
    dupPrevented: parseApiAmount(k.duplicates_prevented_amount),
    dupEvents: k.duplicates_prevented_events,
    fraudAtRisk: parseApiAmount(k.fraud_blocked_amount),
    fraudEvents: k.fraud_blocked_events,
    automationSavings: parseApiAmount(k.automation_savings_amount),
    manualCostBaseline: parseApiAmount(k.manual_cost_per_invoice_baseline) || 30,
    syncSuccess: k.sync_success_pct != null ? parseApiAmount(k.sync_success_pct) : null,
    deadLetter: k.sync_dead_letter_count,
    syncProviders: k.sync_providers_label,
    pastRetention: k.documents_past_retention,
    retentionDays: k.document_retention_days,
    missingDocs: k.missing_supporting_docs,
  };

  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">{moneyPrefix}</span>
      {cfoN0(v)}
    </>
  );

  const touchlessMeterPct =
    K.touchless != null && K.touchlessTarget > 0
      ? kpiMeterWidth((K.touchless / K.touchlessTarget) * 100)
      : null;

  const captureParts = [
    K.captureEmail > 0 ? `Email ${cfoN0(K.captureEmail)}` : null,
    K.captureUpload > 0 ? `Upload ${cfoN0(K.captureUpload)}` : null,
    K.captureWhatsapp > 0 ? `WhatsApp ${cfoN0(K.captureWhatsapp)}` : null,
    K.captureViber > 0 ? `Viber ${cfoN0(K.captureViber)}` : null,
  ].filter(Boolean);

  const tiles: KpiTileDef[] = [
    {
      label: "Documents processed",
      value: (
        <>
          {cfoN0(K.invoicesYTD)}
          <span className="text-base font-medium text-muted-foreground ml-1">posted</span>
        </>
      ),
      foot: (
        <>
          MTD <span className="tnum">{cfoN0(K.invoicesMTD)}</span>
          {captureParts.length > 0 ? (
            <> · {captureParts.join(" · ")}</>
          ) : (
            <> · Process Efficiency report</>
          )}
        </>
      ),
    },
    {
      label: "Straight-through rate",
      value: K.touchless != null ? cfoPct(K.touchless) : "—",
      foot: (
        <>
          Target <span className="tnum">{cfoN0(K.touchlessTarget)}%</span>
          {K.firstPass != null ? (
            <>
              {" "}
              · first-pass <span className="tnum">{cfoPct(K.firstPass)}</span>
            </>
          ) : null}
        </>
      ),
      meter:
        touchlessMeterPct != null
          ? {
              pct: touchlessMeterPct,
              tone: K.touchless != null && K.touchless >= K.touchlessTarget ? "pos" : "warn",
            }
          : K.touchless != null
            ? { pct: kpiMeterWidth(K.touchless), tone: "warn" }
            : undefined,
    },
    {
      label: "First-pass validation",
      value: K.firstPass != null ? cfoPct(K.firstPass) : "—",
      foot: <>No manual field edits or approval holds on first run</>,
      meter: K.firstPass != null ? { pct: kpiMeterWidth(K.firstPass), tone: "pos" } : undefined,
    },
    {
      label: "Avg turnaround time",
      value:
        K.avgProcMins != null ? (
          <>
            {cfoN1(K.avgProcMins)}
            <span className="text-base font-medium text-muted-foreground ml-1">min</span>
          </>
        ) : (
          "—"
        ),
      foot: <>Ingest → posted · manual baseline {cfoN0(K.baselineMins)} min</>,
    },
    {
      label: "Time saved",
      value: (
        <>
          {cfoN0(K.hoursSaved)}
          <span className="text-base font-medium text-muted-foreground ml-1">hrs</span>
        </>
      ),
      foot:
        K.fte != null ? (
          <>
            ≈ <span className="tnum">{cfoN1(K.fte)}</span> FTE capacity released
          </>
        ) : (
          <>vs manual processing baseline</>
        ),
    },
    {
      label: "Automation savings",
      value: cur(K.automationSavings),
      foot: (
        <>
          Manual cost avoided vs {moneyPrefix}
          {cfoN0(K.manualCostBaseline)} / doc baseline
        </>
      ),
    },
    {
      label: "Duplicates blocked",
      value: cur(K.dupPrevented),
      foot: (
        <>
          Pre-ingestion blocks · <span className="tnum">{cfoN0(K.dupEvents)}</span> events
        </>
      ),
    },
    {
      label: "Fraud documents flagged",
      value: cur(K.fraudAtRisk),
      foot: (
        <>
          Open DT-21 · <span className="tnum">{cfoN0(K.fraudEvents)}</span> documents
        </>
      ),
    },
    {
      label: "Ledger sync success",
      value: K.syncSuccess != null ? cfoPct(K.syncSuccess) : "—",
      foot: (
        <>
          {K.deadLetter} dead-letter
          {K.syncProviders ? (
            <>
              {" "}
              · {K.syncProviders}
            </>
          ) : (
            <> · Xero / QuickBooks jobs</>
          )}
        </>
      ),
      meter:
        K.syncSuccess != null
          ? { pct: kpiMeterWidth(K.syncSuccess), tone: "pos" }
          : undefined,
    },
    {
      label: "Vault & compliance",
      value: (
        <>
          {cfoN0(K.vaultDocs)}
          <span className="text-base font-medium text-muted-foreground ml-1">stored</span>
        </>
      ),
      foot: (
        <>
          Missing docs <span className="tnum">{cfoN0(K.missingDocs)}</span>
          {" "}
          · past retention <span className="tnum">{cfoN0(K.pastRetention)}</span>
          {K.retentionDays > 0 ? (
            <>
              {" "}
              ({cfoN0(Math.round(K.retentionDays / 365))} yr policy)
            </>
          ) : null}
        </>
      ),
    },
  ];

  return (
    <div className="kpi-card-grid">
      {tiles.map((t) => (
        <CfoKpiTile key={t.label} {...t} />
      ))}
    </div>
  );
}

function CashForecastChart({ weeks, fillHeight }: { weeks: CashOutlookWeek[]; fillHeight?: boolean }) {
  const data = useMemo(
    () =>
      weeks.map((w) => ({
        label: w.label,
        confirmed: parseApiAmount(w.confirmed_ap),
        probable: parseApiAmount(w.probable_ap),
        recurring: parseApiAmount(w.recurring),
        reimbursements: parseApiAmount(w.reimbursements),
        advances: parseApiAmount(w.advances),
        tax: parseApiAmount(w.tax),
        balance:
          w.available_balance != null ? parseApiAmount(w.available_balance) : null,
      })),
    [weeks]
  );

  const activeStacks = useMemo(
    () =>
      CASH_STACK.filter((segment) =>
        data.some((row) => (row[segment.key as keyof typeof row] as number) > 0)
      ),
    [data]
  );

  const hasBalance = data.some((row) => row.balance != null);

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.cash}
      fill={fillHeight}
      legend={[
        ...activeStacks.map((s) => ({ color: s.color, label: s.label })),
        ...(hasBalance
          ? [{ color: CHART_INK, label: "Bank feed balance", line: true, dashed: true }]
          : []),
      ]}
    >
      <ComposedChart data={data} margin={CHART_MARGIN.cash} barCategoryGap="18%" barGap={2}>
        <CartesianGrid stroke={CHART_GRID} vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={{ stroke: CHART_GRID }}
          tickLine={false}
          interval={0}
          height={32}
        />
        <YAxis
          yAxisId="left"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={cfoAxisCompact}
          width={52}
        />
        {hasBalance ? (
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 10, fill: CHART_AXIS }}
            axisLine={false}
            tickLine={false}
            tickFormatter={cfoAxisCompact}
            width={52}
          />
        ) : null}
        <Tooltip
          content={({ active, payload, label }) => (
            <ChartTooltip active={active} payload={payload} label={label} valueFormatter={(v) => cfoMoney(v)} />
          )}
        />
        {activeStacks.map((s, i) => (
          <Bar
            key={s.key}
            yAxisId="left"
            dataKey={s.key}
            name={s.label}
            stackId="s"
            fill={s.color}
            maxBarSize={34}
            radius={i === activeStacks.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
          />
        ))}
        {hasBalance ? (
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="balance"
            name="Bank feed balance"
            stroke={CHART_INK}
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 3"
            connectNulls={false}
          />
        ) : null}
      </ComposedChart>
    </CfoChartBlock>
  );
}

function AgeingChart({ buckets, fillHeight }: { buckets: ApAgeingBucket[]; fillHeight?: boolean }) {
  const data = useMemo(
    () => buckets.map((a) => ({ bucket: a.bucket, value: parseApiAmount(a.amount) })),
    [buckets]
  );
  return (
    <CfoChartShell height={CHART_HEIGHT.ageing} fill={fillHeight}>
      <BarChart layout="vertical" data={data} margin={CHART_MARGIN.ageing} barCategoryGap="22%">
        <CartesianGrid stroke={CHART_GRID} horizontal={false} />
        <XAxis
          type="number"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={cfoAxisCompact}
        />
        <YAxis
          type="category"
          dataKey="bucket"
          tick={{ fontSize: 10.5, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          width={92}
        />
        <Tooltip
          content={({ active, payload, label }) => (
            <ChartTooltip active={active} payload={payload} label={label} valueFormatter={(v) => `${cfoMoney(v)} AUD`} />
          )}
        />
        <Bar dataKey="value" radius={[0, 3, 3, 0]} maxBarSize={26}>
          {data.map((_, i) => (
            <Cell key={i} fill={AGEING_COLORS[i % AGEING_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </CfoChartShell>
  );
}

const CHART_DEPARTMENT_LIMIT = 8;

function CfoChartEmpty({
  message,
  height = 260,
}: {
  message: string;
  height?: number;
}) {
  return (
    <div
      className="flex items-center justify-center px-6 text-center text-sm text-muted-foreground"
      style={{ height, minHeight: height }}
    >
      {message}
    </div>
  );
}

function collapseDepartmentsForChart(departments: BudgetDepartmentRow[]): BudgetDepartmentRow[] {
  const sorted = [...departments].sort(
    (a, b) => parseApiAmount(b.budget) - parseApiAmount(a.budget)
  );
  if (sorted.length <= CHART_DEPARTMENT_LIMIT) return sorted;

  const head = sorted.slice(0, CHART_DEPARTMENT_LIMIT);
  const tail = sorted.slice(CHART_DEPARTMENT_LIMIT);
  const other = tail.reduce(
    (acc, row) => ({
      budget: acc.budget + parseApiAmount(row.budget),
      actual: acc.actual + parseApiAmount(row.actual),
      committed: acc.committed + parseApiAmount(row.committed),
    }),
    { budget: 0, actual: 0, committed: 0 }
  );

  return [
    ...head,
    {
      name: "Other",
      budget: String(other.budget),
      actual: String(other.actual),
      committed: String(other.committed),
      owner: "",
    },
  ];
}

function BudgetChart({
  departments,
  fillHeight,
}: {
  departments: BudgetDepartmentRow[];
  fillHeight?: boolean;
}) {
  const { theme } = useTheme();
  const dark = theme === "dark";
  const stackColors = budgetStackColors(dark);

  const chartDepartments = useMemo(() => collapseDepartmentsForChart(departments), [departments]);
  const data = useMemo<BudgetChartRow[]>(
    () =>
      chartDepartments.map((d) => {
        const budget = parseApiAmount(d.budget);
        const actual = parseApiAmount(d.actual);
        const committed = parseApiAmount(d.committed);
        const utilised = budget > 0 ? (actual / budget) * 100 : 0;
        const encumbered = actual + committed;
        const { chartActual, chartCommitted, headroom } = budgetStackSegments(
          actual,
          committed,
          budget
        );
        return {
          name: cfoBudgetAxisLabel(d.name),
          fullName: d.name,
          budget,
          actual,
          committed,
          remaining: Math.max(0, budget - encumbered),
          utilisedPct: utilised,
          over: budget > 0 && actual > budget,
          chartActual,
          chartCommitted,
          headroom,
        };
      }),
    [chartDepartments]
  );

  const chartHeight = useMemo(
    () => Math.min(560, Math.max(320, data.length * 58 + 56)),
    [data.length]
  );

  const xMax = useMemo(() => {
    if (!data.length) return 1;
    const peak = Math.max(...data.map((row) => Math.max(row.budget, row.actual + row.committed)));
    return peak > 0 ? peak * 1.08 : 1;
  }, [data]);

  const hasSpend = useMemo(
    () => data.some((row) => row.actual > 0 || row.committed > 0),
    [data]
  );

  if (departments.length === 0) {
    return (
      <CfoChartEmpty
        height={CHART_HEIGHT.tall}
        message="No department budgets configured for this period. Set up Parent GL + Sub-GL budgets under Settings → GL Budget."
      />
    );
  }

  return (
    <div
      className={cn(
        "cfo-budget-stack-chart min-w-0",
        fillHeight && "flex flex-1 flex-col min-h-0"
      )}
    >
      <CfoChartLegend
        items={[
          { color: stackColors.actual, label: "Actual spend" },
          { color: stackColors.committed, label: "Committed (in-flight claims)" },
          { color: stackColors.budgetTrack, label: "Remaining budget" },
        ]}
      />
      {!hasSpend ? (
        <p className="px-3 pb-2 text-[11px] text-muted-foreground">
          No actual or committed spend recorded for this period yet — bars show full remaining budget.
        </p>
      ) : null}
      <CfoChartShell height={chartHeight} fill={fillHeight} className="px-2">
        <BarChart
          data={data}
          layout="vertical"
          margin={CHART_MARGIN.budgetHorizontal}
          barCategoryGap="18%"
        >
          <CartesianGrid
            stroke={CHART_GRID}
            horizontal={false}
            strokeDasharray="3 6"
            strokeOpacity={0.8}
          />
          <XAxis
            type="number"
            domain={[0, xMax]}
            tick={{ fontSize: 10, fill: CHART_AXIS }}
            axisLine={false}
            tickLine={false}
            tickFormatter={cfoAxisCompact}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 10.5, fill: CHART_AXIS }}
            axisLine={false}
            tickLine={false}
            width={112}
          />
          <Tooltip
            cursor={{ fill: "hsl(var(--nav-accent) / 0.08)", radius: 6 }}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as BudgetChartRow | undefined;
              return <BudgetChartTooltip active={active} row={row} />;
            }}
          />
          <Bar
            dataKey="chartActual"
            name="Actual"
            stackId="budget"
            barSize={28}
            fill={stackColors.actual}
            isAnimationActive={false}
            radius={[0, 0, 0, 0]}
          >
            {data.map((row) => (
              <Cell
                key={`actual-${row.fullName}`}
                fill={row.over ? stackColors.actualOver : stackColors.actual}
                stroke={stackColors.segmentStroke}
                strokeWidth={dark ? 1 : 0}
              />
            ))}
          </Bar>
          <Bar
            dataKey="chartCommitted"
            name="Committed"
            stackId="budget"
            barSize={28}
            fill={stackColors.committed}
            isAnimationActive={false}
            radius={[0, 0, 0, 0]}
          >
            {data.map((row) => (
              <Cell
                key={`committed-${row.fullName}`}
                fill={stackColors.committed}
                stroke={stackColors.segmentStroke}
                strokeWidth={dark ? 1 : 0}
              />
            ))}
          </Bar>
          <Bar
            dataKey="headroom"
            name="Remaining budget"
            stackId="budget"
            barSize={28}
            fill={stackColors.budgetTrack}
            isAnimationActive={false}
            radius={[0, 6, 6, 0]}
          >
            {data.map((row) => (
              <Cell
                key={`headroom-${row.fullName}`}
                fill={stackColors.budgetTrack}
                stroke={stackColors.budgetTrackStroke}
                strokeWidth={dark ? 1 : 0}
              />
            ))}
            <LabelList
              dataKey="utilisedPct"
              position="right"
              formatter={(value: number) => cfoPct(value)}
              style={{ fontSize: 10, fontWeight: 600, fill: stackColors.labelFill }}
            />
          </Bar>
        </BarChart>
      </CfoChartShell>
    </div>
  );
}

function cfoVendorAxisLabel(name: string, maxLen = 14) {
  if (name.length <= maxLen) return name;
  return `${name.slice(0, maxLen - 1)}…`;
}

function paretoRiskFill(risk: string, dark: boolean) {
  const palette = dark ? KPI_MODULE_CHART_DARK : KPI_MODULE_CHART_LIGHT;
  if (risk === "High") return palette.rose;
  if (risk === "Medium") return palette.rust;
  return palette.blue;
}

type ParetoChartRow = {
  key: string;
  name: string;
  fullName: string;
  spend: number;
  invoiceCount: number;
  poBackedPct: number | null;
  cycleDays: number | null;
  cumulative: number;
  risk: string;
  bankChange: boolean;
};

function VendorConcentrationTooltip({
  active,
  row,
}: {
  active?: boolean;
  row?: ParetoChartRow;
}) {
  if (!active || !row) return null;
  const rows = [
    { label: "Total invoiced", value: cfoN0(row.spend), valueClass: "text-foreground" },
    {
      label: "Invoices",
      value: cfoN0(row.invoiceCount),
      valueClass: "text-foreground",
    },
    {
      label: "PO reference",
      value: row.poBackedPct != null ? `${cfoN1(row.poBackedPct)}%` : "—",
      valueClass: "text-foreground",
    },
    {
      label: "Pay cycle",
      value: row.cycleDays != null ? `${cfoN1(row.cycleDays)} d` : "—",
      valueClass: "text-foreground",
    },
    {
      label: "Cumulative share",
      value: cfoPct(row.cumulative),
      valueClass: "text-[hsl(var(--nav-accent))]",
    },
  ] as const;

  return (
    <div className="chart-tooltip cfo-budget-chart-tooltip">
      <p className="chart-tooltip-label">{row.fullName}</p>
      <dl className="cfo-budget-chart-tooltip-grid">
        {rows.map((item) => (
          <Fragment key={item.label}>
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className={cn("tnum font-medium", item.valueClass)}>{item.value}</dd>
          </Fragment>
        ))}
      </dl>
      {row.bankChange ? (
        <p className="chart-tooltip-value text-destructive mt-2 mb-0">Bank detail change flagged</p>
      ) : null}
      {row.risk === "Medium" ? (
        <p className="chart-tooltip-value tnum mt-2 mb-0 text-muted-foreground">
          Low PO reference coverage
        </p>
      ) : null}
    </div>
  );
}

function paretoActiveIndexFromState(
  state:
    | {
        isTooltipActive?: boolean;
        activeTooltipIndex?: number | string;
        activeLabel?: string | number;
      }
    | undefined,
  rows: ParetoChartRow[]
): number | null {
  if (!state?.isTooltipActive) return null;
  const rawIndex = state.activeTooltipIndex;
  if (typeof rawIndex === "number" && rawIndex >= 0) return rawIndex;
  if (typeof rawIndex === "string") {
    const parsed = Number.parseInt(rawIndex, 10);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  if (state.activeLabel != null) {
    const label = String(state.activeLabel);
    const idx = rows.findIndex((row) => row.name === label);
    if (idx >= 0) return idx;
  }
  return null;
}

function ParetoChart({
  vendors,
  periodLabel,
  fillHeight,
}: {
  vendors: VendorConcentrationRow[];
  periodLabel?: string;
  fillHeight?: boolean;
}) {
  const { theme } = useTheme();
  const dark = theme === "dark";
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const totalSpend = useMemo(
    () => vendors.reduce((sum, v) => sum + parseApiAmount(v.spend), 0),
    [vendors]
  );
  const data = useMemo<ParetoChartRow[]>(() => {
    let cum = 0;
    return vendors.map((v, index) => {
      const spend = parseApiAmount(v.spend);
      cum += spend;
      return {
        key: `vendor-${index}`,
        name: cfoVendorAxisLabel(v.name),
        fullName: v.name,
        spend,
        invoiceCount: v.invoice_count,
        poBackedPct: v.po_backed_pct != null ? parseApiAmount(v.po_backed_pct) : null,
        cycleDays: v.cycle_days != null ? parseApiAmount(v.cycle_days) : null,
        cumulative: totalSpend > 0 ? (cum / totalSpend) * 100 : 0,
        risk: v.risk_level,
        bankChange: v.bank_change_flag,
      };
    });
  }, [vendors, totalSpend]);

  if (vendors.length === 0) {
    return (
      <CfoChartEmpty
        height={CHART_HEIGHT.tall}
        message={
          periodLabel
            ? `No vendor spend in Vendor Spend Summary for ${periodLabel}.`
            : "No vendor spend recorded for the selected period."
        }
      />
    );
  }

  const spendFill = dark ? KPI_MODULE_CHART_DARK.blue : KPI_MODULE_CHART_LIGHT.blue;
  const lineColor = dark ? KPI_MODULE_CHART_DARK.cyan : CHART_INK;

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.tall}
      fill={fillHeight}
      className="cfo-pareto-chart"
      legend={[
        { color: spendFill, label: "Total invoiced" },
        { color: paretoRiskFill("High", dark), label: "Bank detail change" },
        { color: paretoRiskFill("Medium", dark), label: "Low PO coverage" },
        { color: lineColor, label: "Cumulative share", line: true },
      ]}
    >
      <ComposedChart
        data={data}
        margin={CHART_MARGIN.pareto}
        barCategoryGap="24%"
        barGap={4}
        onMouseMove={(state) => {
          const idx = paretoActiveIndexFromState(state, data);
          if (idx != null) setActiveIndex(idx);
        }}
        onMouseLeave={() => setActiveIndex(null)}
      >
        <CartesianGrid stroke={CHART_GRID} vertical={false} strokeDasharray="3 6" strokeOpacity={0.8} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={{ stroke: CHART_GRID }}
          tickLine={false}
          angle={-40}
          textAnchor="end"
          height={72}
          interval={0}
        />
        <YAxis
          yAxisId="left"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={cfoAxisCompact}
          width={52}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${v}%`}
          width={40}
        />
        <Tooltip
          cursor={{ fill: "transparent", stroke: "transparent" }}
          shared
          content={({ active, payload }) => {
            const row = payload?.[0]?.payload as ParetoChartRow | undefined;
            return <VendorConcentrationTooltip active={active} row={row} />;
          }}
        />
        <Bar
          yAxisId="left"
          dataKey="spend"
          name="Spend"
          radius={[4, 4, 0, 0]}
          maxBarSize={24}
        >
          {data.map((entry, index) => (
            <Cell
              key={entry.key}
              fill={paretoRiskFill(entry.risk, dark)}
              opacity={activeIndex == null || activeIndex === index ? 1 : 0.28}
            />
          ))}
        </Bar>
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="cumulative"
          name="Cumulative %"
          stroke={lineColor}
          strokeWidth={2}
          isAnimationActive={false}
          activeDot={false}
          dot={{ r: 2.5, fill: lineColor, strokeWidth: 0 }}
        />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="cumulative"
          stroke="transparent"
          strokeWidth={14}
          dot={false}
          activeDot={false}
          isAnimationActive={false}
          legendType="none"
          tooltipType="none"
          style={{ pointerEvents: "stroke" }}
        />
        {activeIndex != null && data[activeIndex] ? (
          <ReferenceDot
            x={data[activeIndex].name}
            y={data[activeIndex].cumulative}
            yAxisId="right"
            ifOverflow="visible"
            isFront
            shape={(props: { cx?: number; cy?: number }) => {
              const { cx, cy } = props;
              if (cx == null || cy == null) return <g />;
              return (
                <g>
                  <circle cx={cx} cy={cy} r={11} fill="hsl(var(--nav-accent) / 0.22)" />
                  <circle
                    cx={cx}
                    cy={cy}
                    r={5.5}
                    fill={lineColor}
                    stroke="hsl(var(--nav-accent))"
                    strokeWidth={2.5}
                  />
                </g>
              );
            }}
          />
        ) : null}
      </ComposedChart>
    </CfoChartBlock>
  );
}

function trendAxisDomain(values: number[], padRatio = 0.12): [number, number] {
  if (values.length === 0) return [0, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    const pad = Math.max(1, Math.abs(min) * 0.15 || 1);
    return [Math.max(0, min - pad), max + pad];
  }
  const span = max - min;
  return [Math.max(0, min - span * padRatio), max + span * padRatio];
}

type TrendChartRow = {
  label: string;
  dpo: number | null;
  stp: number | null;
};

function ProcessEfficiencyTrendTooltip({
  active,
  row,
}: {
  active?: boolean;
  row?: TrendChartRow;
}) {
  if (!active || !row) return null;
  return (
    <div className="rounded-md border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-semibold text-foreground mb-1.5">{row.label}</p>
      <div className="space-y-1 text-muted-foreground">
        <div className="flex items-center justify-between gap-4">
          <span>DPO</span>
          <span className="tnum font-medium text-foreground">
            {row.dpo != null ? `${cfoN1(row.dpo)} days` : "—"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span>Straight-through</span>
          <span className="tnum font-medium text-foreground">
            {row.stp != null ? cfoPct(row.stp) : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function ProcessEfficiencyTrendChart({
  points,
  stpTarget,
  fillHeight,
}: {
  points: ProcessEfficiencyTrendPoint[];
  stpTarget: number;
  fillHeight?: boolean;
}) {
  const data = useMemo<TrendChartRow[]>(
    () =>
      points.map((point) => ({
        label: point.label,
        dpo: point.dpo_days != null ? parseApiAmount(point.dpo_days) : null,
        stp: point.stp_pct != null ? parseApiAmount(point.stp_pct) : null,
      })),
    [points]
  );

  const hasDpo = data.some((row) => row.dpo != null);
  const hasStp = data.some((row) => row.stp != null);

  const dpoDomain = useMemo(
    () => trendAxisDomain(data.flatMap((row) => (row.dpo != null ? [row.dpo] : []))),
    [data]
  );
  const stpDomain = useMemo(() => {
    const values = data.flatMap((row) => (row.stp != null ? [row.stp] : []));
    if (stpTarget > 0) values.push(stpTarget);
    const domain = trendAxisDomain(values);
    return [Math.max(0, domain[0]), Math.min(100, domain[1])] as [number, number];
  }, [data, stpTarget]);

  if (!hasDpo && !hasStp) {
    return (
      <CfoChartEmpty
        height={CHART_HEIGHT.tall}
        message="No DPO or straight-through data for the rolling 12-month window yet."
      />
    );
  }

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.tall}
      fill={fillHeight}
      legend={[
        { color: KPI_MODULE_CHART_LIGHT.blue, label: "DPO (days)", line: true },
        { color: "hsl(var(--success))", label: "Straight-through %", line: true, dashed: true },
      ]}
    >
      <ComposedChart data={data} margin={CHART_MARGIN.trend}>
        <CartesianGrid stroke={CHART_GRID} vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={{ stroke: CHART_GRID }}
          tickLine={false}
          height={32}
        />
        <YAxis
          yAxisId="left"
          domain={dpoDomain}
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          width={36}
          hide={!hasDpo}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          domain={stpDomain}
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${v}%`}
          width={40}
          hide={!hasStp}
        />
        <Tooltip
          content={({ active, payload }) => {
            const row = payload?.[0]?.payload as TrendChartRow | undefined;
            return <ProcessEfficiencyTrendTooltip active={active} row={row} />;
          }}
        />
        {hasDpo ? (
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="dpo"
            name="DPO (days)"
            stroke={KPI_MODULE_CHART_LIGHT.blue}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ) : null}
        {hasStp ? (
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="stp"
            name="Straight-through %"
            stroke="hsl(var(--success))"
            strokeWidth={1.6}
            dot={false}
            strokeDasharray="4 3"
            connectNulls
          />
        ) : null}
      </ComposedChart>
    </CfoChartBlock>
  );
}

function ProcessEfficiencyTrendSection({
  tenantName,
  period,
}: {
  tenantName?: string;
  period: DashboardPeriod;
}) {
  const { data, isLoading, isError, error } = useProcessEfficiencyTrends(period);

  const panelMeta = useMemo(() => {
    if (!data) return undefined;
    const target = cfoN0(parseApiAmount(data.summary.stp_target_pct));
    const env = data.meta.environment_label ?? tenantName;
    return `Process Efficiency · ${data.meta.period_label} · STP target ${target}%${env ? ` · ${env}` : ""}`;
  }, [data, tenantName]);

  if (isLoading && !data) {
    return (
      <PanelCard
        className="min-w-0 cfo-split-panel"
        title="DPO & straight-through trend"
        meta={panelMeta}
        flushBody
        stretchBody
      >
        <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} fill />
      </PanelCard>
    );
  }

  if (isError || !data) {
    return (
      <PanelCard
        className="min-w-0 cfo-split-panel"
        title="DPO & straight-through trend"
        flushBody
        stretchBody
      >
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load process efficiency trends. ${error.message}`
              : "Could not load process efficiency trends."
          }
        />
      </PanelCard>
    );
  }

  const summary = data.summary;
  const latestDpo =
    summary.latest_dpo_days != null ? cfoN1(parseApiAmount(summary.latest_dpo_days)) : "—";
  const latestStp =
    summary.latest_stp_pct != null ? cfoPct(parseApiAmount(summary.latest_stp_pct)) : "—";
  const hasData = summary.months_with_dpo > 0 || summary.months_with_stp > 0;

  return (
    <PanelCard
      className="min-w-0 cfo-split-panel"
      title="DPO & straight-through trend"
      meta={panelMeta}
      flushBody
      stretchBody
      foot={
        hasData ? (
          <>
            <span>
              Latest DPO <strong className="tnum text-foreground">{latestDpo}</strong> days
            </span>
            <span>
              Latest STP <strong className="tnum text-foreground">{latestStp}</strong>
            </span>
            <span>
              Target{" "}
              <strong className="tnum text-foreground">
                {cfoN0(parseApiAmount(summary.stp_target_pct))}%
              </strong>
            </span>
          </>
        ) : undefined
      }
    >
      <ProcessEfficiencyTrendChart
        points={data.points}
        stpTarget={parseApiAmount(summary.stp_target_pct)}
        fillHeight
      />
    </PanelCard>
  );
}

function AgeingStats({ buckets, total }: { buckets: ApAgeingBucket[]; total: number }) {
  const rows: { label: string; value: string; strong?: boolean }[] = [
    ...buckets.map((a) => {
      const value = parseApiAmount(a.amount);
      return {
        label: a.bucket,
        value: `${cfoN0(value)} (${cfoPct(total > 0 ? (value / total) * 100 : 0)})`,
      };
    }),
    { label: "Total balance due", value: cfoN0(total), strong: true },
  ];

  return (
    <div className="divide-y divide-border/60 bg-muted/20">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-3 px-4 py-2.5 text-sm">
          <span className={cn("text-muted-foreground", row.strong && "font-semibold text-foreground")}>
            {row.label}
          </span>
          <span className="tnum font-semibold text-foreground">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

const ALERTS_PAGE_SIZE = 5;

function AlertsList({ alerts, fillHeight }: { alerts: CfoAlertRow[]; fillHeight?: boolean }) {
  const [visibleCount, setVisibleCount] = useState(ALERTS_PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(ALERTS_PAGE_SIZE);
  }, [alerts]);

  const sevBorder = (sev: string) =>
    sev === "high" ? "border-l-destructive" : sev === "med" ? "border-l-[hsl(var(--warning))]" : "border-l-[hsl(var(--nav-accent))]";

  if (alerts.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center px-4 text-sm text-muted-foreground",
          fillHeight ? "flex-1 min-h-[260px]" : "max-h-[356px] min-h-[356px]"
        )}
      >
        No active alerts or threshold breaches
      </div>
    );
  }

  const visible = alerts.slice(0, visibleCount);
  const remaining = alerts.length - visibleCount;
  const hasMore = remaining > 0;
  const canCollapse = visibleCount > ALERTS_PAGE_SIZE;

  return (
    <div className={cn("flex flex-col", fillHeight ? "flex-1 min-h-0 h-full" : "min-h-[356px]")}>
      <div
        className={cn(
          "flex-1 overflow-y-auto divide-y divide-border/60",
          !fillHeight && "max-h-[320px] min-h-[320px]"
        )}
      >
        {visible.map((a) => (
          <div key={`${a.source}-${a.title}`} className={cn("px-4 py-3 border-l-[3px]", sevBorder(a.severity))}>
            <p className="text-sm font-semibold text-foreground m-0">{a.title}</p>
            <p className="text-xs text-muted-foreground mt-1 mb-0">{a.detail}</p>
            {a.meta ? <p className="text-[11px] text-muted-foreground/80 mt-1.5 mb-0">{a.meta}</p> : null}
          </div>
        ))}
      </div>
      {(hasMore || canCollapse) && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border/60 px-4 py-2.5">
          <span className="text-xs text-muted-foreground">
            Showing {visible.length} of {alerts.length}
          </span>
          <div className="flex items-center gap-3">
            {canCollapse ? (
              <button
                type="button"
                className="text-xs font-medium text-muted-foreground hover:text-foreground"
                onClick={() => setVisibleCount(ALERTS_PAGE_SIZE)}
              >
                Show first {ALERTS_PAGE_SIZE}
              </button>
            ) : null}
            {hasMore ? (
              <button
                type="button"
                className="text-xs font-medium text-[hsl(var(--nav-accent))] hover:underline"
                onClick={() =>
                  setVisibleCount((count) => Math.min(count + ALERTS_PAGE_SIZE, alerts.length))
                }
              >
                Next {Math.min(ALERTS_PAGE_SIZE, remaining)}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function AlertsThresholdSection({ period }: { period: DashboardPeriod }) {
  const { data, isLoading, isError, error } = useCfoAlerts(period);

  const panelMeta = useMemo(() => {
    if (!data) return undefined;
    const { active_count, high_count } = data.summary;
    if (active_count === 0) return "No active alerts · engine thresholds applied";
    const highPart = high_count > 0 ? ` · ${high_count} high` : "";
    return `${active_count} active${highPart} · engine thresholds applied`;
  }, [data]);

  if (isLoading && !data) {
    return (
      <PanelCard
        className="min-w-0 cfo-split-panel"
        title="Alerts & threshold breaches"
        meta={panelMeta}
        flushBody
        stretchBody
      >
        <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} fill />
      </PanelCard>
    );
  }

  if (isError || !data) {
    return (
      <PanelCard className="min-w-0 cfo-split-panel" title="Alerts & threshold breaches" flushBody stretchBody>
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load alerts. ${error.message}`
              : "Could not load alerts."
          }
        />
      </PanelCard>
    );
  }

  return (
    <PanelCard
      className="min-w-0 cfo-split-panel"
      title="Alerts & threshold breaches"
      meta={panelMeta}
      flushBody
      stretchBody
    >
      <AlertsList alerts={data.alerts} fillHeight />
    </PanelCard>
  );
}

function CashLiabilityOutlookSection({
  tenantName,
  period,
}: {
  tenantName?: string;
  period: DashboardPeriod;
}) {
  const { data, isLoading, isError, error } = useCashLiabilityOutlook(period);

  const hint = useMemo(() => {
    const meta = data?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    const asOf = meta.as_of
      ? new Date(meta.as_of).toLocaleDateString("en-AU", {
          day: "numeric",
          month: "short",
          year: "numeric",
        })
      : "";
    return `Cash Forecast report · ${meta.horizon_weeks}-week horizon from ${asOf} · ${meta.currency}${env ? ` · ${env}` : ""}`;
  }, [data?.meta, tenantName]);

  if (isLoading && !data) {
    return (
      <>
        <SectionHead title="Cash forecast & payables" hint={hint} />
        <div className="cfo-split-panel-grid cfo-split-panel-grid--cash">
          <PanelCard
            className="min-w-0 cfo-split-panel"
            title="Cash Forecast — 13-week outflow"
            flushBody
            stretchBody
          >
            <CfoChartPanelSkeleton height={CHART_HEIGHT.cash} fill />
          </PanelCard>
          <PanelCard className="min-w-0 cfo-split-panel" title="Aged Payables" flushBody stretchBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.ageing} fill />
          </PanelCard>
        </div>
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        <SectionHead title="Cash forecast & payables" hint={hint} />
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load cash forecast & payables. ${error.message}`
              : "Could not load cash forecast & payables."
          }
        />
      </>
    );
  }

  const summary = data.summary;
  const ageingTotal = parseApiAmount(data.ap_ageing_total);
  const openingCash =
    summary.opening_cash_balance != null
      ? parseApiAmount(summary.opening_cash_balance)
      : null;
  const coverage =
    summary.coverage_ratio != null ? `${cfoN1(parseApiAmount(summary.coverage_ratio))}×` : "—";
  const peakLabel = summary.peak_week_label
    ? `w/c ${summary.peak_week_label}`
    : "—";
  const activeForecastLayers = CASH_STACK.filter((segment) =>
    data.weeks.some((week) => parseApiAmount(week[segment.apiField]) > 0)
  );
  const forecastMeta =
    activeForecastLayers.length > 0
      ? activeForecastLayers.map((layer) => layer.label).join(" · ")
      : "Payment Schedule + team expense payouts · same logic as Cash Forecast report";

  return (
    <>
      <SectionHead title="Cash forecast & payables" hint={hint} />
      <div className="cfo-split-panel-grid cfo-split-panel-grid--cash">
        <PanelCard
          className="min-w-0 cfo-split-panel"
          title="Cash Forecast — 13-week outflow"
          meta={forecastMeta}
          flushBody
          stretchBody
          foot={
            <>
              <span>
                Next week{" "}
                <strong className="tnum text-foreground">
                  {cfoN0(parseApiAmount(summary.next_week_outflow))}
                </strong>
              </span>
              <span>
                Horizon total{" "}
                <strong className="tnum text-foreground">
                  {cfoN0(parseApiAmount(summary.total_horizon_outflow))}
                </strong>
              </span>
              <span>
                Peak week {peakLabel}{" "}
                <strong className="tnum text-foreground">
                  {cfoN0(parseApiAmount(summary.peak_week_outflow))}
                </strong>
              </span>
              {openingCash != null ? (
                <>
                  <span>
                    Bank balance{" "}
                    <strong className="tnum text-foreground">{cfoN0(openingCash)}</strong>
                  </span>
                  <span>
                    Next-week coverage <strong className="text-foreground">{coverage}</strong>
                  </span>
                </>
              ) : (
                <span>Import bank feeds to show balance line</span>
              )}
            </>
          }
        >
          <CashForecastChart weeks={data.weeks} fillHeight />
        </PanelCard>

        <PanelCard
          className="min-w-0 cfo-split-panel"
          title="Aged Payables"
          meta={`Balance due ${cfoN0(ageingTotal)} · netted ledger remaining`}
          flushBody
          stretchBody
          aside={<AgeingStats buckets={data.ap_ageing} total={ageingTotal} />}
        >
          <AgeingChart buckets={data.ap_ageing} fillHeight />
        </PanelCard>
      </div>
    </>
  );
}

function budgetPanelTitle(groupLabel: string): string {
  if (groupLabel === "GL account") return "Budget vs Actual — by GL account";
  if (groupLabel === "department") return "Budget vs Actual — by department";
  return `Budget vs Actual — by ${groupLabel}`;
}

function BudgetConcentrationRiskSection({
  tenantName,
  period,
}: {
  tenantName?: string;
  period: DashboardPeriod;
}) {
  const { data, isLoading, isError, error } = useBudgetConcentrationRisk(period);

  const hint = useMemo(() => {
    const meta = data?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    return `Budget vs Actual · Vendor Spend Summary · ${meta.period_label} · ${meta.currency}${env ? ` · ${env}` : ""}`;
  }, [data?.meta, tenantName]);

  if (isLoading && !data) {
    return (
      <>
        <SectionHead title="Budget & vendor spend" hint={hint} />
        <div className="cfo-split-panel-grid cfo-split-panel-grid--budget">
          <PanelCard className="min-w-0 cfo-split-panel" title="Budget vs Actual — by GL account" flushBody stretchBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} fill />
          </PanelCard>
          <PanelCard className="min-w-0 cfo-split-panel" title="Vendor Spend Summary" flushBody stretchBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} fill />
          </PanelCard>
        </div>
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        <SectionHead title="Budget & vendor spend" hint={hint} />
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load budget & vendor spend. ${error.message}`
              : "Could not load budget & vendor spend."
          }
        />
      </>
    );
  }

  const summary = data.vendor_summary;
  const top10Pct =
    summary.top10_concentration_pct != null
      ? cfoN1(parseApiAmount(summary.top10_concentration_pct))
      : "—";
  const nonPoPct =
    summary.non_po_spend_pct != null ? cfoN1(parseApiAmount(summary.non_po_spend_pct)) : "—";
  const budgetSummary = data.budget_summary;
  const utilisation =
    budgetSummary.utilisation_pct != null
      ? cfoN1(parseApiAmount(budgetSummary.utilisation_pct))
      : "—";
  const remaining = parseApiAmount(budgetSummary.remaining);
  const periodLabel = data.meta.period_label;
  const budgetTitle = budgetPanelTitle(data.meta.budget_group_label);

  return (
    <>
      <SectionHead title="Budget & vendor spend" hint={hint} />
      <div className="cfo-split-panel-grid cfo-split-panel-grid--budget">
        <PanelCard
          className="min-w-0 cfo-split-panel"
          title={budgetTitle}
          meta="Department budgets · committed = in-flight team expense claims"
          flushBody
          stretchBody
          foot={
            data.departments.length > 0 ? (
              <>
                <span>
                  Budget{" "}
                  <strong className="tnum text-foreground">
                    {cfoN0(parseApiAmount(budgetSummary.budget))}
                  </strong>
                </span>
                <span>
                  Actual{" "}
                  <strong className="tnum text-foreground">
                    {cfoN0(parseApiAmount(budgetSummary.actual))}
                  </strong>
                </span>
                <span>
                  Committed{" "}
                  <strong className="tnum text-foreground">
                    {cfoN0(parseApiAmount(budgetSummary.committed))}
                  </strong>
                </span>
                <span>
                  Remaining{" "}
                  <strong
                    className={cn(
                      "tnum",
                      remaining < 0 ? "text-destructive" : "text-foreground"
                    )}
                  >
                    {cfoN0(remaining)}
                  </strong>
                </span>
                <span>
                  Utilised <strong className="text-foreground">{utilisation}%</strong>
                </span>
              </>
            ) : undefined
          }
        >
          <BudgetChart departments={data.departments} fillHeight />
        </PanelCard>
        <PanelCard
          className="min-w-0 cfo-split-panel"
          title="Vendor Spend Summary"
          meta={
            top10Pct !== "—"
              ? `Top 10 vendors · ${top10Pct}% of spend · ${periodLabel}`
              : `No vendor spend · ${periodLabel}`
          }
          flushBody
          stretchBody
          foot={
            <>
              <span>
                Non-PO invoices <strong className="tnum text-foreground">{nonPoPct}%</strong>
              </span>
              <span>
                Vendor master registered{" "}
                <strong className="text-foreground">
                  {summary.contracted_in_top10} of {Math.min(data.vendors.length, 10)}
                </strong>
              </span>
              <span>
                {summary.high_risk_count > 0
                  ? summary.high_risk_count === 1
                    ? "1 bank detail change flagged"
                    : `${summary.high_risk_count} bank detail changes flagged`
                  : "No bank detail change flags"}
              </span>
            </>
          }
        >
          <ParetoChart vendors={data.vendors} periodLabel={periodLabel} fillHeight />
        </PanelCard>
      </div>
    </>
  );
}

export function DashboardView({
  tenantName,
  period,
}: {
  tenantName?: string;
  period: DashboardPeriod;
}) {
  const { data: liquidity } = usePositionLiquidity(period);
  const { data: efficiency } = useEfficiencyAutomation(period);

  const positionHint = useMemo(() => {
    const meta = liquidity?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    return `All figures ${meta.currency}, consolidated, ${meta.period_label}${env ? ` · ${env}` : ""}`;
  }, [liquidity?.meta, tenantName]);

  const efficiencyHint = useMemo(() => {
    const meta = efficiency?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    return `Process Efficiency · ${meta.period_label}${env ? ` · ${env}` : ""}`;
  }, [efficiency?.meta, tenantName]);

  return (
    <div data-testid="dashboard-view">
      <SectionHead
        title="Position & liquidity"
        hint={positionHint}
      />
      <PrimaryKpis period={period} />

      <SectionHead title="Efficiency & automation value" hint={efficiencyHint} />
      <SecondaryKpis period={period} />

      <CashLiabilityOutlookSection tenantName={tenantName} period={period} />

      <BudgetConcentrationRiskSection tenantName={tenantName} period={period} />

      <SectionHead title="Trends & alerts" />
      <div className="cfo-split-panel-grid cfo-split-panel-grid--trends">
        <ProcessEfficiencyTrendSection tenantName={tenantName} period={period} />
        <AlertsThresholdSection period={period} />
      </div>
    </div>
  );
}

const PERIOD_OPTIONS = DASHBOARD_PERIOD_OPTIONS;

export function DashboardFilters({
  period,
  onPeriodChange,
}: {
  period: DashboardPeriod;
  onPeriodChange: (period: DashboardPeriod) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={period}
        onValueChange={(value) => onPeriodChange(value as DashboardPeriod)}
        options={PERIOD_OPTIONS}
        data-testid="select-dashboard-period"
      />
    </div>
  );
}
