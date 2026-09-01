import { useMemo, useState, type ReactElement, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { Skeleton } from "@/components/skeleton/Skeleton";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { CFO_DEMO } from "@/lib/cfoDemoData";
import { usePositionLiquidity } from "@/hooks/usePositionLiquidity";
import { useEfficiencyAutomation } from "@/hooks/useEfficiencyAutomation";
import { useCashLiabilityOutlook } from "@/hooks/useCashLiabilityOutlook";
import { useBudgetConcentrationRisk } from "@/hooks/useBudgetConcentrationRisk";
import type {
  ApAgeingBucket,
  BudgetDepartmentRow,
  CashOutlookWeek,
  VendorConcentrationRow,
} from "@/api/types";
import {
  cfoAxisCompact,
  cfoCompact,
  cfoMoney,
  cfoN0,
  cfoN1,
  cfoN2,
  cfoPct,
  cfoRag,
  cfoRagLabel,
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

const BUDGET_BULLET_RADIUS = 6;
const BUDGET_BULLET_MIN_SEG_PX = 4;

type BudgetBulletColors = {
  budgetTrack: string;
  actual: string;
  actualOver: string;
  committed: string;
};

function budgetBulletColors(dark: boolean): BudgetBulletColors {
  const palette = dark ? KPI_MODULE_CHART_DARK : KPI_MODULE_CHART_LIGHT;
  return {
    budgetTrack: dark ? "hsl(var(--muted-foreground) / 0.32)" : "hsl(var(--muted-foreground) / 0.16)",
    actual: palette.blue,
    actualOver: palette.rose,
    committed: palette.sage,
  };
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
  trackMax: number;
};

type BudgetBulletBarProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: BudgetChartRow;
  colors: BudgetBulletColors;
};

function BudgetBulletBar({ x = 0, y = 0, width = 0, height = 0, payload, colors }: BudgetBulletBarProps) {
  if (!payload || width <= 0 || payload.trackMax <= 0) return null;

  const barH = Math.max(14, Math.min(26, height * 0.58));
  const yCenter = y + (height - barH) / 2;
  const scale = width / payload.trackMax;
  const budgetPx = Math.max(payload.budget * scale, payload.budget > 0 ? 6 : 0);
  const actualPx =
    payload.actual > 0 ? Math.max(payload.actual * scale, BUDGET_BULLET_MIN_SEG_PX) : 0;
  const committedPx =
    payload.committed > 0 ? Math.max(payload.committed * scale, BUDGET_BULLET_MIN_SEG_PX) : 0;
  const actualColor = payload.over ? colors.actualOver : colors.actual;

  return (
    <g>
      <rect
        x={x}
        y={yCenter}
        width={budgetPx}
        height={barH}
        rx={BUDGET_BULLET_RADIUS}
        fill={colors.budgetTrack}
      />
      {actualPx > 0 ? (
        <rect
          x={x}
          y={yCenter}
          width={actualPx}
          height={barH}
          rx={BUDGET_BULLET_RADIUS}
          fill={actualColor}
        />
      ) : null}
      {committedPx > 0 ? (
        <rect
          x={x + actualPx}
          y={yCenter}
          width={committedPx}
          height={barH}
          rx={BUDGET_BULLET_RADIUS}
          fill={colors.committed}
        />
      ) : null}
    </g>
  );
}

function BudgetChartTooltip({
  active,
  row,
}: {
  active?: boolean;
  row?: BudgetChartRow;
}) {
  if (!active || !row) return null;
  const remaining = row.budget - row.actual - row.committed;
  return (
    <div className="chart-tooltip cfo-budget-chart-tooltip">
      <p className="chart-tooltip-label">{row.fullName}</p>
      <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 mt-1.5 text-[11px]">
        <span className="text-muted-foreground">Budget</span>
        <span className="tnum font-medium text-foreground text-right">{cfoN0(row.budget)}</span>
        <span className="text-muted-foreground">Actual</span>
        <span className={cn("tnum font-medium text-right", row.over && "text-destructive")}>
          {cfoN0(row.actual)}
        </span>
        <span className="text-muted-foreground">Committed</span>
        <span className="tnum font-medium text-foreground text-right">{cfoN0(row.committed)}</span>
        <span className="text-muted-foreground">Remaining</span>
        <span
          className={cn(
            "tnum font-medium text-right",
            remaining < 0 ? "text-destructive" : "text-foreground"
          )}
        >
          {cfoN0(remaining)}
        </span>
      </div>
      <p className="chart-tooltip-value tnum mt-2 mb-0 text-[hsl(var(--nav-accent))]">
        {cfoPct(row.utilisedPct)} utilised
        {row.over ? " · over budget" : ""}
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
  children,
  className,
}: {
  height: number;
  children: ReactElement;
  className?: string;
}) {
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
  legend,
  children,
  className,
}: {
  height: number;
  legend?: LegendItem[];
  children: ReactElement;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      {legend ? <CfoChartLegend items={legend} /> : null}
      <CfoChartShell height={height} className={legend ? "px-1" : undefined}>
        {children}
      </CfoChartShell>
    </div>
  );
}

const CASH_STACK = [
  { key: "confirmed", label: "Confirmed AP", color: KPI_MODULE_CHART_LIGHT.blue },
  { key: "probable", label: "Probable AP", color: KPI_MODULE_CHART_LIGHT.violet },
  { key: "recurring", label: "Recurring", color: KPI_MODULE_CHART_LIGHT.teal },
  { key: "reimbursements", label: "Reimbursements", color: KPI_MODULE_CHART_LIGHT.sage },
  { key: "advances", label: "Advances", color: KPI_MODULE_CHART_LIGHT.rust },
  { key: "tax", label: "Tax / BAS", color: KPI_MODULE_CHART_LIGHT.rose },
] as const;

type SortDir = "asc" | "desc";

type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right";
  sortValue?: (row: T) => string | number;
  render: (row: T) => ReactNode;
};

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
  className,
}: {
  title: string;
  meta?: string;
  children: ReactNode;
  foot?: ReactNode;
  aside?: ReactNode;
  flushBody?: boolean;
  className?: string;
}) {
  return (
    <Card className={cn("dash-card--elevated overflow-hidden flex flex-col", className)}>
      <div className="flex flex-wrap items-baseline gap-2 border-b border-border/60 px-4 py-3 shrink-0">
        <h3 className="text-sm font-semibold m-0">{title}</h3>
        {meta ? <span className="text-xs text-muted-foreground ml-auto text-right max-w-[55%]">{meta}</span> : null}
      </div>
      <div className={cn(flushBody ? "min-w-0" : "p-4 min-w-0")}>{children}</div>
      {aside ? <div className="min-w-0 shrink-0">{aside}</div> : null}
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
      ? "bg-destructive"
      : meter?.tone === "warn"
        ? "bg-[hsl(var(--warning))]"
        : meter?.tone === "pos"
          ? "bg-[hsl(var(--success))]"
          : "bg-[hsl(var(--nav-accent))]";

  return (
    <Card className="kpi-card kpi-card--elevated p-4 min-w-0">
      <p className="text-xs font-medium text-muted-foreground truncate leading-snug mb-1.5">
        {label}
      </p>
      <p className="text-[1.375rem] font-semibold tnum tracking-tight leading-none text-foreground">
        {value}
      </p>
      {foot ? <div className="mt-2 text-xs text-muted-foreground flex flex-wrap gap-1">{foot}</div> : null}
      {meter ? (
        <div className="h-1 rounded-full bg-muted overflow-hidden mt-2.5">
          <div
            className={cn("h-full rounded-full", meterClass)}
            style={{ width: `${Math.min(100, meter.pct)}%` }}
          />
        </div>
      ) : null}
    </Card>
  );
}

const PRIMARY_KPI_TILE_COUNT = 10;
const SECONDARY_KPI_TILE_COUNT = 10;

function CfoKpiGridSkeleton({ count }: { count: number }) {
  return (
    <div
      className="grid gap-3 grid-cols-2 lg:grid-cols-5"
      aria-busy="true"
      aria-label="Loading KPIs"
    >
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

function CfoChartPanelSkeleton({ height }: { height: number }) {
  return (
    <div className="px-4 py-4" aria-busy="true" aria-label="Loading chart">
      <Skeleton className="h-4 w-48 mb-4" />
      <Skeleton style={{ height, minHeight: height }} className="w-full rounded-md" />
    </div>
  );
}

function parseApiAmount(value: string | null | undefined): number {
  if (value == null || value === "") return 0;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function PrimaryKpis() {
  const { data, isLoading, isError, error } = usePositionLiquidity();

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
  const dpo = k.dpo_days != null ? parseApiAmount(k.dpo_days) : null;
  const dpoPrior = k.dpo_prior_year_days != null ? parseApiAmount(k.dpo_prior_year_days) : null;
  const K = {
    apOutstanding: parseApiAmount(k.ap_outstanding),
    approvedNotPaid: parseApiAmount(k.approved_not_paid),
    due7: parseApiAmount(k.due_next_7_days),
    due14: parseApiAmount(k.due_next_14_days),
    due30: parseApiAmount(k.due_next_30_days),
    overdue: parseApiAmount(k.overdue),
    overduePct: k.overdue_pct != null ? parseApiAmount(k.overdue_pct) : null,
    overdueThreshold: parseApiAmount(k.overdue_threshold_pct) || 10,
    dpo,
    dpoPrior,
    onTimeRate:
      k.on_time_payment_rate_pct != null ? parseApiAmount(k.on_time_payment_rate_pct) : null,
    discountRate:
      k.discount_capture_rate_pct != null ? parseApiAmount(k.discount_capture_rate_pct) : null,
    utilisation:
      k.budget_utilisation_pct != null ? parseApiAmount(k.budget_utilisation_pct) : null,
    actualYTD: parseApiAmount(k.budget_actual),
    budgetYTD: parseApiAmount(k.budget_allocated),
    advancesOutstanding: parseApiAmount(k.advances_outstanding),
    advancesOverdue: parseApiAmount(k.advances_overdue),
    advancesOverdueEmployees: k.advances_overdue_employees,
    openExceptions: k.open_exceptions_count,
    exceptionAtRisk: parseApiAmount(k.open_exceptions_at_risk),
    claimsPending: k.claims_pending_count,
    claimsPendingValue: parseApiAmount(k.claims_pending_value),
    top10Concentration:
      k.vendor_top10_concentration_pct != null
        ? parseApiAmount(k.vendor_top10_concentration_pct)
        : null,
    nonPoSpend:
      k.vendor_non_po_spend_pct != null ? parseApiAmount(k.vendor_non_po_spend_pct) : null,
  };

  const currency = data.meta.currency ?? "AUD";
  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">{currency === "AUD" ? "A$" : `${currency} `}</span>
      {cfoN0(v)}
    </>
  );

  const tiles: KpiTileDef[] = [
    { label: "AP outstanding", value: cur(K.apOutstanding), foot: <>Approved not paid <strong className="tnum text-foreground">{cfoN0(K.approvedNotPaid)}</strong></> },
    { label: "Due next 7 days", value: cur(K.due7), foot: <>14 d <span className="tnum">{cfoN0(K.due14)}</span> · 30 d <span className="tnum">{cfoN0(K.due30)}</span></> },
    {
      label: "Overdue",
      value: cur(K.overdue),
      foot:
        K.overduePct != null ? (
          <>
            <span className="text-destructive font-medium tnum">{cfoPct(K.overduePct)}</span> of AP · threshold{" "}
            {cfoPct(K.overdueThreshold)}
          </>
        ) : (
          <>Threshold {cfoPct(K.overdueThreshold)}</>
        ),
      meter: K.overduePct != null ? { pct: K.overduePct * 4, tone: "neg" } : undefined,
    },
    {
      label: "Days payable outstanding",
      value:
        K.dpo != null ? (
          <>
            {cfoN1(K.dpo)}
            <span className="text-base font-medium text-muted-foreground ml-1">days</span>
          </>
        ) : (
          "—"
        ),
      foot:
        K.dpoPrior != null && K.dpo != null && K.dpoPrior > 0 ? (
          <>
            <span className={K.dpoPrior - K.dpo >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}>
              <span className="font-medium">
                {K.dpoPrior - K.dpo >= 0 ? "▼" : "▲"} {cfoN1(Math.abs(K.dpoPrior - K.dpo))}
              </span>
            </span>{" "}
            vs PY {cfoN1(K.dpoPrior)}
          </>
        ) : (
          <>vs prior year —</>
        ),
    },
    {
      label: "On-time payment rate",
      value: K.onTimeRate != null ? cfoPct(K.onTimeRate) : "—",
      foot:
        K.discountRate != null ? (
          <>
            Discount capture <span className="tnum">{cfoPct(K.discountRate)}</span>
          </>
        ) : (
          <>
            Discount capture <span className="text-muted-foreground">not tracked</span>
          </>
        ),
      meter: K.onTimeRate != null ? { pct: K.onTimeRate, tone: "pos" } : undefined,
    },
    {
      label: "Budget utilisation",
      value: K.utilisation != null ? cfoPct(K.utilisation) : "—",
      foot: (
        <>
          Actual <span className="tnum">{cfoCompact(K.actualYTD)}</span> of{" "}
          <span className="tnum">{cfoCompact(K.budgetYTD)}</span>{" "}
          <span className="text-muted-foreground">(excl. committed)</span>
        </>
      ),
      meter: K.utilisation != null ? { pct: K.utilisation, tone: "warn" } : undefined,
    },
    { label: "Advances outstanding", value: cur(K.advancesOutstanding), foot: <><span className="text-destructive font-medium tnum">{cfoN0(K.advancesOverdue)}</span> overdue · {K.advancesOverdueEmployees} employees</> },
    { label: "Open exceptions", value: <>{cfoN0(K.openExceptions)}<span className="text-base font-medium text-muted-foreground ml-1">items</span></>, foot: <><span className="tnum">{cfoN0(K.exceptionAtRisk)}</span> at risk</> },
    { label: "Claims pending approval", value: <>{cfoN0(K.claimsPending)}<span className="text-base font-medium text-muted-foreground ml-1">claims</span></>, foot: <><span className="tnum">{cfoN0(K.claimsPendingValue)}</span> awaiting sign-off</> },
    {
      label: "Vendor concentration",
      value: K.top10Concentration != null ? cfoPct(K.top10Concentration) : "—",
      foot:
        K.nonPoSpend != null ? (
          <>Top 10 · non-PO {cfoPct(K.nonPoSpend)}</>
        ) : (
          <>Top 10 vendors</>
        ),
      meter: K.top10Concentration != null ? { pct: K.top10Concentration, tone: "warn" } : undefined,
    },
  ];

  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
      {tiles.map((t) => (
        <CfoKpiTile key={t.label} {...t} />
      ))}
    </div>
  );
}

function SecondaryKpis() {
  const { data, isLoading, isError, error } = useEfficiencyAutomation();

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
    costPerInvoice: k.cost_per_invoice != null ? parseApiAmount(k.cost_per_invoice) : null,
    costBaseline: parseApiAmount(k.manual_cost_per_invoice_baseline) || 30,
    costImprovement:
      k.cost_improvement_pct != null ? parseApiAmount(k.cost_improvement_pct) : null,
    avgProcMins: k.avg_processing_minutes != null ? parseApiAmount(k.avg_processing_minutes) : null,
    baselineMins: parseApiAmount(k.manual_processing_minutes_baseline) || 182,
    hoursSaved: parseApiAmount(k.hours_saved_ytd),
    fte: k.fte_equivalent != null ? parseApiAmount(k.fte_equivalent) : null,
    invoicesYTD: k.documents_processed_ytd,
    invoicesMTD: k.documents_processed_mtd,
    vaultDocs: k.vault_documents_total,
    dupPrevented: parseApiAmount(k.duplicates_prevented_amount),
    dupEvents: k.duplicates_prevented_events,
    fraudAtRisk: parseApiAmount(k.fraud_blocked_amount),
    fraudEvents: k.fraud_blocked_events,
    discountCaptured: k.discount_captured != null ? parseApiAmount(k.discount_captured) : null,
    discountAvailable: k.discount_available != null ? parseApiAmount(k.discount_available) : null,
    valueDelivered:
      k.total_value_delivered != null ? parseApiAmount(k.total_value_delivered) : null,
    syncSuccess: k.sync_success_pct != null ? parseApiAmount(k.sync_success_pct) : null,
    deadLetter: k.sync_dead_letter_count,
    syncProviders: k.sync_providers_label,
    pastRetention: k.documents_past_retention,
    missingDocs: k.missing_supporting_docs,
  };

  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">{moneyPrefix}</span>
      {cfoN0(v)}
    </>
  );

  const touchlessFoot = (
    <>
      Target <span className="tnum">{cfoN0(K.touchlessTarget)}%</span>
      {K.firstPass != null ? (
        <>
          {" "}
          · First-pass <span className="tnum">{cfoPct(K.firstPass)}</span>
        </>
      ) : null}
      <span className="text-muted-foreground"> · STP proxy</span>
    </>
  );

  const tiles: KpiTileDef[] = [
    {
      label: "Touchless processing",
      value: K.touchless != null ? cfoPct(K.touchless) : "—",
      foot: touchlessFoot,
      meter: K.touchless != null ? { pct: K.touchless, tone: "warn" } : undefined,
    },
    {
      label: "Cost per invoice",
      value:
        K.costPerInvoice != null ? (
          <>
            <span className="text-muted-foreground text-base font-medium mr-0.5">{moneyPrefix}</span>
            {cfoN2(K.costPerInvoice)}
          </>
        ) : (
          "—"
        ),
      foot: (
        <>
          Baseline <span className="tnum">{cfoN2(K.costBaseline)}</span>
          {K.costImprovement != null ? (
            <>
              {" "}
              · <span className="text-emerald-600 dark:text-emerald-400 tnum">−{cfoPct(K.costImprovement)}</span>
            </>
          ) : null}
        </>
      ),
    },
    {
      label: "Avg processing time",
      value:
        K.avgProcMins != null ? (
          <>
            {cfoN1(K.avgProcMins)}
            <span className="text-base font-medium text-muted-foreground ml-1">min</span>
          </>
        ) : (
          "—"
        ),
      foot: <>Baseline {cfoN0(K.baselineMins)} min · posted</>,
    },
    {
      label: "Hours saved YTD",
      value: cfoN0(K.hoursSaved),
      foot: K.fte != null ? <><strong>{cfoN1(K.fte)} FTE</strong> released</> : <>FTE —</>,
    },
    {
      label: "Documents processed",
      value: cfoN0(K.invoicesYTD),
      foot: (
        <>
          MTD <span className="tnum">{cfoN0(K.invoicesMTD)}</span>
          {" "}
          · vault <span className="tnum">{cfoN0(K.vaultDocs)}</span>
        </>
      ),
    },
    {
      label: "Duplicates prevented",
      value: cur(K.dupPrevented),
      foot: (
        <>
          Fraud blocked <span className="tnum">{cfoN0(K.fraudAtRisk)}</span>
          {K.dupEvents > 0 || K.fraudEvents > 0 ? (
            <>
              {" "}
              · over <span className="tnum">{K.dupEvents + K.fraudEvents}</span> events
            </>
          ) : null}
        </>
      ),
    },
    {
      label: "Discount captured",
      value:
        K.discountCaptured != null ? (
          cur(K.discountCaptured)
        ) : (
          <span className="text-muted-foreground text-lg">Not tracked</span>
        ),
      foot:
        K.discountAvailable != null ? (
          <>
            Available <span className="tnum">{cfoN0(K.discountAvailable)}</span>
          </>
        ) : (
          <span className="text-muted-foreground">No discount-term data</span>
        ),
    },
    {
      label: "Total value delivered",
      value:
        K.valueDelivered != null ? (
          cur(K.valueDelivered)
        ) : (
          <span className="text-muted-foreground text-lg">Pending</span>
        ),
      foot:
        K.valueDelivered != null
          ? "Automation & prevention YTD"
          : "Withheld until discount capture tracked",
    },
    {
      label: "Sync success",
      value: K.syncSuccess != null ? cfoPct(K.syncSuccess) : "—",
      foot: (
        <>
          {K.deadLetter} dead-letter
          {K.syncProviders ? <> · {K.syncProviders}</> : null}
        </>
      ),
      meter: K.syncSuccess != null ? { pct: K.syncSuccess, tone: "pos" } : undefined,
    },
    {
      label: "Documents past retention",
      value: cfoN0(K.pastRetention),
      foot: (
        <>
          Missing docs <span className="tnum">{cfoN0(K.missingDocs)}</span>
        </>
      ),
    },
  ];

  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
      {tiles.map((t) => (
        <CfoKpiTile key={t.label} {...t} />
      ))}
    </div>
  );
}

function RagBadge({ utilisedPct }: { utilisedPct: number }) {
  const rag = cfoRag(utilisedPct);
  const tone = rag === "r" ? pillTones.bad : rag === "a" ? pillTones.amber : pillTones.ok;
  return <StatusPill className={tone}>{cfoRagLabel(utilisedPct)}</StatusPill>;
}

function CfoSortableTable<T>({
  columns,
  rows,
  foot,
  getRowClass,
  rowKey,
}: {
  columns: Column<T>[];
  rows: T[];
  foot?: ReactNode;
  getRowClass?: (row: T) => string | undefined;
  rowKey: (row: T, index: number) => string;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return rows;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = col.sortValue!(a);
      const vb = col.sortValue!(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [columns, rows, sortDir, sortKey]);

  const onSort = (col: Column<T>) => {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir("asc");
    }
  };

  return (
    <div className="overflow-x-auto overscroll-x-contain">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card z-10">
          <tr className="text-left text-xs text-muted-foreground border-b border-border">
            {columns.map((col) => {
              const sortedCol = sortKey === col.key;
              return (
                <th
                  key={col.key}
                  className={cn(
                    "py-2 px-3 font-medium whitespace-nowrap",
                    col.align === "right" && "text-right",
                    col.sortValue && "cursor-pointer select-none hover:text-foreground"
                  )}
                  onClick={col.sortValue ? () => onSort(col) : undefined}
                >
                  {col.header}
                  {col.sortValue ? (
                    <span
                      className={cn(
                        "ml-1 text-[9px] inline-block",
                        sortedCol ? "opacity-100 text-[hsl(var(--nav-accent))]" : "opacity-0"
                      )}
                    >
                      {sortedCol && sortDir === "desc" ? "▼" : "▲"}
                    </span>
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              className={cn(
                "row-band border-b border-border/60",
                getRowClass?.(row) === "alert" && "bg-destructive/[0.03]"
              )}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "py-2 px-3 text-foreground/90 whitespace-nowrap",
                    col.align === "right" && "text-right tnum"
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {foot ? (
          <tfoot>
            <tr className="border-t border-border bg-muted/30 font-semibold text-foreground">
              {foot}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}

function CashForecastChart({ weeks }: { weeks: CashOutlookWeek[] }) {
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

  const hasBalance = data.some((row) => row.balance != null);

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.cash}
      legend={[
        ...CASH_STACK.map((s) => ({ color: s.color, label: s.label })),
        ...(hasBalance
          ? [{ color: CHART_INK, label: "Available balance", line: true, dashed: true }]
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
        {CASH_STACK.map((s, i) => (
          <Bar
            key={s.key}
            yAxisId="left"
            dataKey={s.key}
            name={s.label}
            stackId="s"
            fill={s.color}
            maxBarSize={34}
            radius={i === CASH_STACK.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
          />
        ))}
        {hasBalance ? (
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="balance"
            name="Available balance"
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

function AgeingChart({ buckets }: { buckets: ApAgeingBucket[] }) {
  const data = useMemo(
    () => buckets.map((a) => ({ bucket: a.bucket, value: parseApiAmount(a.amount) })),
    [buckets]
  );
  return (
    <CfoChartShell height={CHART_HEIGHT.ageing}>
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

function BudgetChart({ departments }: { departments: BudgetDepartmentRow[] }) {
  const { theme } = useTheme();
  const dark = theme === "dark";
  const bulletColors = budgetBulletColors(dark);

  const chartDepartments = useMemo(() => collapseDepartmentsForChart(departments), [departments]);
  const data = useMemo<BudgetChartRow[]>(
    () =>
      chartDepartments.map((d) => {
        const budget = parseApiAmount(d.budget);
        const actual = parseApiAmount(d.actual);
        const committed = parseApiAmount(d.committed);
        const utilised = budget > 0 ? (actual / budget) * 100 : 0;
        const encumbered = actual + committed;
        return {
          name: cfoBudgetAxisLabel(d.name),
          fullName: d.name,
          budget,
          actual,
          committed,
          remaining: Math.max(0, budget - encumbered),
          utilisedPct: utilised,
          over: budget > 0 && actual > budget,
          trackMax: Math.max(budget, encumbered, 1),
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
    const peak = Math.max(...data.map((row) => row.trackMax));
    return peak > 0 ? peak * 1.08 : 1;
  }, [data]);

  if (departments.length === 0) {
    return (
      <CfoChartEmpty
        height={CHART_HEIGHT.tall}
        message="No GL budgets are configured for this period. Add budgets under Team Expenses to populate this chart."
      />
    );
  }

  return (
    <div className="cfo-budget-bullet-chart min-w-0">
      <CfoChartLegend
        items={[
          { color: bulletColors.budgetTrack, label: "Budget envelope" },
          { color: bulletColors.actual, label: "Actual" },
          { color: bulletColors.committed, label: "Committed" },
        ]}
      />
      <CfoChartShell height={chartHeight} className="px-2">
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
            dataKey="trackMax"
            name="Budget utilisation"
            barSize={34}
            fill="transparent"
            isAnimationActive={false}
            shape={(rawProps: unknown) => {
              const props = rawProps as BudgetBulletBarProps;
              return <BudgetBulletBar {...props} colors={bulletColors} />;
            }}
          >
            <LabelList
              dataKey="utilisedPct"
              position="right"
              formatter={(value: number) => cfoPct(value)}
              className="fill-muted-foreground"
              style={{ fontSize: 10, fontWeight: 600 }}
            />
          </Bar>
        </BarChart>
      </CfoChartShell>
    </div>
  );
}

function ParetoChart({ vendors }: { vendors: VendorConcentrationRow[] }) {
  const totalSpend = useMemo(
    () => vendors.reduce((sum, v) => sum + parseApiAmount(v.spend), 0),
    [vendors]
  );
  const data = useMemo(() => {
    let cum = 0;
    return vendors.map((v) => {
      const spend = parseApiAmount(v.spend);
      cum += spend;
      return {
        name: v.name.split(" ")[0],
        fullName: v.name,
        spend,
        invoiceCount: v.invoice_count,
        poBackedPct: v.po_backed_pct != null ? parseApiAmount(v.po_backed_pct) : null,
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
        message="No vendor spend recorded for the current financial year."
      />
    );
  }

  const riskFill = (risk: string) =>
    risk === "High" ? KPI_MODULE_CHART_LIGHT.rose : risk === "Medium" ? KPI_MODULE_CHART_LIGHT.rust : KPI_MODULE_CHART_LIGHT.blue;

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.tall}
      legend={[
        { color: KPI_MODULE_CHART_LIGHT.blue, label: "Spend YTD" },
        { color: CHART_INK, label: "Cumulative % of spend", line: true },
      ]}
    >
      <ComposedChart data={data} margin={CHART_MARGIN.pareto} barCategoryGap="24%" barGap={4}>
        <CartesianGrid stroke={CHART_GRID} vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={{ stroke: CHART_GRID }}
          tickLine={false}
          angle={-45}
          textAnchor="end"
          height={64}
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
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const row = data.find((d) => d.name === label);
            if (!row) return null;
            return (
              <div className="chart-tooltip">
                <p className="chart-tooltip-label">{row.fullName}</p>
                <p className="chart-tooltip-value tnum">{cfoN0(row.spend)}</p>
                <p className="chart-tooltip-value tnum text-muted-foreground">
                  {cfoN0(row.invoiceCount)} invoice{row.invoiceCount === 1 ? "" : "s"}
                </p>
                {row.poBackedPct != null ? (
                  <p className="chart-tooltip-value tnum text-muted-foreground">
                    {cfoN1(row.poBackedPct)}% PO-backed
                  </p>
                ) : null}
                <p className="chart-tooltip-value tnum text-muted-foreground">
                  {cfoPct(row.cumulative)} cumulative
                </p>
                {row.bankChange ? (
                  <p className="chart-tooltip-value text-destructive">Bank change flagged</p>
                ) : null}
              </div>
            );
          }}
        />
        <Bar yAxisId="left" dataKey="spend" name="Spend YTD" radius={[3, 3, 0, 0]} maxBarSize={22}>
          {data.map((entry) => (
            <Cell key={entry.fullName} fill={riskFill(entry.risk)} />
          ))}
        </Bar>
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="cumulative"
          name="Cumulative %"
          stroke={CHART_INK}
          strokeWidth={1.5}
          dot={{ r: 2, fill: CHART_INK }}
        />
      </ComposedChart>
    </CfoChartBlock>
  );
}

function TrendChart() {
  const data = CFO_DEMO.dpoTrend.labels.map((label, i) => ({
    label,
    dpo: CFO_DEMO.dpoTrend.dpo[i],
    touchless: CFO_DEMO.dpoTrend.touchless[i],
  }));

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.tall}
      legend={[
        { color: KPI_MODULE_CHART_LIGHT.blue, label: "DPO (days)", line: true },
        { color: "hsl(var(--success))", label: "Touchless %", line: true, dashed: true },
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
          domain={[38, 50]}
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          width={36}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          domain={[50, 90]}
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `${v}%`}
          width={40}
        />
        <Tooltip
          content={({ active, payload, label }) => (
            <ChartTooltip active={active} payload={payload} label={label} valueFormatter={(v) => cfoN1(v)} />
          )}
        />
        <Line
          yAxisId="left"
          type="monotone"
          dataKey="dpo"
          name="DPO (days)"
          stroke={KPI_MODULE_CHART_LIGHT.blue}
          strokeWidth={2}
          dot={false}
        />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="touchless"
          name="Touchless %"
          stroke="hsl(var(--success))"
          strokeWidth={1.6}
          dot={false}
          strokeDasharray="4 3"
        />
      </ComposedChart>
    </CfoChartBlock>
  );
}

function DeptTable({ departments }: { departments: BudgetDepartmentRow[] }) {
  const rows = useMemo(
    () =>
      departments.map((d) => ({
        name: d.name,
        budget: parseApiAmount(d.budget),
        actual: parseApiAmount(d.actual),
        committed: parseApiAmount(d.committed),
        owner: d.owner || "—",
      })),
    [departments]
  );
  const totals = rows.reduce(
    (a, d) => ({ budget: a.budget + d.budget, actual: a.actual + d.actual, committed: a.committed + d.committed }),
    { budget: 0, actual: 0, committed: 0 }
  );

  if (rows.length === 0) {
    return (
      <CfoChartEmpty
        message="No budget rows to display. Configure GL budgets on Team Expenses to track encumbrance."
      />
    );
  }

  return (
    <CfoSortableTable
      rows={rows}
      rowKey={(r) => r.name}
      getRowClass={(d) => (d.budget > 0 && cfoRag((d.actual / d.budget) * 100) === "r" ? "alert" : undefined)}
      columns={[
        { key: "name", header: "Cost centre", sortValue: (d) => d.name, render: (d) => <span className="font-medium text-foreground">{d.name}</span> },
        { key: "budget", header: "Budget", align: "right", sortValue: (d) => d.budget, render: (d) => cfoN0(d.budget) },
        { key: "actual", header: "Actual", align: "right", sortValue: (d) => d.actual, render: (d) => cfoN0(d.actual) },
        { key: "committed", header: "Committed", align: "right", sortValue: (d) => d.committed, render: (d) => cfoN0(d.committed) },
        {
          key: "remaining",
          header: "Remaining",
          align: "right",
          sortValue: (d) => d.budget - d.actual - d.committed,
          render: (d) => {
            const rem = d.budget - d.actual - d.committed;
            return <span className={rem < 0 ? "text-destructive font-medium" : ""}>{cfoN0(rem)}</span>;
          },
        },
        { key: "utilised", header: "Utilised", align: "right", sortValue: (d) => (d.budget > 0 ? (d.actual / d.budget) * 100 : 0), render: (d) => cfoPct(d.budget > 0 ? (d.actual / d.budget) * 100 : 0) },
        { key: "rag", header: "RAG", sortValue: (d) => cfoRagLabel(d.budget > 0 ? (d.actual / d.budget) * 100 : 0), render: (d) => <RagBadge utilisedPct={d.budget > 0 ? (d.actual / d.budget) * 100 : 0} /> },
        { key: "owner", header: "Owner", sortValue: (d) => d.owner, render: (d) => d.owner },
      ]}
      foot={
        <>
          <td className="py-2 px-3 font-semibold">Total</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.budget)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.actual)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.committed)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.budget - totals.actual - totals.committed)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoPct(totals.budget > 0 ? (totals.actual / totals.budget) * 100 : 0)}</td>
          <td colSpan={2} />
        </>
      }
    />
  );
}

function VendorTable({ vendors }: { vendors: VendorConcentrationRow[] }) {
  const riskTone = (risk: string) =>
    risk === "High" ? pillTones.bad : risk === "Medium" ? pillTones.amber : pillTones.ok;

  const rows = useMemo(
    () =>
      vendors.map((v) => ({
        name: v.name,
        spend: parseApiAmount(v.spend),
        invoices: v.invoice_count,
        cycle: v.cycle_days != null ? parseApiAmount(v.cycle_days) : null,
        po: v.po_backed_pct != null ? parseApiAmount(v.po_backed_pct) : null,
        risk: v.risk_level,
        flag: v.bank_change_flag ? "Bank change" : undefined,
      })),
    [vendors]
  );

  if (rows.length === 0) {
    return (
      <CfoChartEmpty
        message="No vendor spend recorded for the current financial year."
      />
    );
  }

  return (
    <CfoSortableTable
      rows={rows}
      rowKey={(v) => v.name}
      getRowClass={(v) => (v.risk === "High" ? "alert" : undefined)}
      columns={[
        {
          key: "name",
          header: "Vendor",
          sortValue: (v) => v.name,
          render: (v) => (
            <span className="font-medium text-foreground inline-flex items-center gap-2 flex-wrap">
              {v.name}
              {v.flag ? <StatusPill className={pillTones.bad}>Bank change</StatusPill> : null}
            </span>
          ),
        },
        { key: "spend", header: "Spend YTD", align: "right", sortValue: (v) => v.spend, render: (v) => cfoN0(v.spend) },
        { key: "invoices", header: "Invoices", align: "right", sortValue: (v) => v.invoices, render: (v) => cfoN0(v.invoices) },
        {
          key: "cycle",
          header: "Cycle (d)",
          align: "right",
          sortValue: (v) => v.cycle ?? -1,
          render: (v) => (v.cycle != null ? cfoN1(v.cycle) : "—"),
        },
        {
          key: "po",
          header: "PO-backed",
          align: "right",
          sortValue: (v) => v.po ?? -1,
          render: (v) => (v.po != null ? `${cfoN1(v.po)}%` : "—"),
        },
        { key: "risk", header: "Risk", sortValue: (v) => v.risk, render: (v) => <StatusPill className={riskTone(v.risk)}>{v.risk}</StatusPill> },
      ]}
    />
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
    { label: "Total outstanding", value: cfoN0(total), strong: true },
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

function AlertsList() {
  const sevBorder = (sev: string) =>
    sev === "high" ? "border-l-destructive" : sev === "med" ? "border-l-[hsl(var(--warning))]" : "border-l-[hsl(var(--nav-accent))]";

  return (
    <div className="max-h-[356px] min-h-[356px] overflow-y-auto divide-y divide-border/60">
      {CFO_DEMO.alerts.map((a) => (
        <div key={a.title} className={cn("px-4 py-3 border-l-[3px]", sevBorder(a.sev))}>
          <p className="text-sm font-semibold text-foreground m-0">{a.title}</p>
          <p className="text-xs text-muted-foreground mt-1 mb-0">{a.detail}</p>
          <p className="text-[11px] text-muted-foreground/80 mt-1.5 mb-0">{a.meta}</p>
        </div>
      ))}
    </div>
  );
}

function CashLiabilityOutlookSection({ tenantName }: { tenantName?: string }) {
  const { data, isLoading, isError, error } = useCashLiabilityOutlook();

  const hint = useMemo(() => {
    const meta = data?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    return `13-week horizon from ${meta.as_of} · ${meta.currency}${env ? ` · ${env}` : ""}`;
  }, [data?.meta, tenantName]);

  if (isLoading && !data) {
    return (
      <>
        <SectionHead title="Cash & liability outlook" hint={hint} />
        <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <PanelCard title="13-week rolling cash outflow forecast" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.cash} />
          </PanelCard>
          <PanelCard title="AP ageing" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.ageing} />
          </PanelCard>
        </div>
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        <SectionHead title="Cash & liability outlook" hint={hint} />
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load cash & liability outlook. ${error.message}`
              : "Could not load cash & liability outlook."
          }
        />
      </>
    );
  }

  const summary = data.summary;
  const ageingTotal = parseApiAmount(data.ap_ageing_total);
  const coverage =
    summary.coverage_ratio != null ? `${cfoN1(parseApiAmount(summary.coverage_ratio))}×` : "—";
  const peakLabel = summary.peak_week_label
    ? `w/c ${summary.peak_week_label}`
    : "—";

  return (
    <>
      <SectionHead title="Cash & liability outlook" hint={hint} />
      <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PanelCard
          title="13-week rolling cash outflow forecast"
          meta="Confirmed, probable, recurring, reimbursements, advances, tax · cumulative line"
          flushBody
          foot={
            <>
              <span>
                Next week{" "}
                <strong className="tnum text-foreground">
                  {cfoN0(parseApiAmount(summary.next_week_outflow))}
                </strong>
              </span>
              <span>
                13-week total{" "}
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
              <span>
                Coverage ratio <strong className="text-foreground">{coverage}</strong>
              </span>
            </>
          }
        >
          <CashForecastChart weeks={data.weeks} />
        </PanelCard>

        <PanelCard
          title="AP ageing"
          meta={`Total ${cfoN0(ageingTotal)}`}
          flushBody
          aside={<AgeingStats buckets={data.ap_ageing} total={ageingTotal} />}
        >
          <AgeingChart buckets={data.ap_ageing} />
        </PanelCard>
      </div>
    </>
  );
}

function BudgetConcentrationRiskSection({ tenantName }: { tenantName?: string }) {
  const { data, isLoading, isError, error } = useBudgetConcentrationRisk();

  const hint = useMemo(() => {
    const meta = data?.meta;
    if (!meta) return undefined;
    const env = meta.environment_label ?? tenantName;
    return `${meta.period_label} · ${meta.currency}${env ? ` · ${env}` : ""}`;
  }, [data?.meta, tenantName]);

  if (isLoading && !data) {
    return (
      <>
        <SectionHead title="Budget, concentration & risk" hint={hint} />
        <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <PanelCard title="Budget vs actual vs committed — by department" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} />
          </PanelCard>
          <PanelCard title="Vendor concentration" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} />
          </PanelCard>
        </div>
        <div className="grid gap-4 mt-4">
          <PanelCard title="Budget vs actual vs committed (encumbrance)" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} />
          </PanelCard>
          <PanelCard title="Top vendors" flushBody>
            <CfoChartPanelSkeleton height={CHART_HEIGHT.tall} />
          </PanelCard>
        </div>
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        <SectionHead title="Budget, concentration & risk" hint={hint} />
        <CfoKpiLoadError
          message={
            error?.message
              ? `Could not load budget & concentration figures. ${error.message}`
              : "Could not load budget & concentration figures."
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
  const budgetTitle = `by ${data.meta.budget_group_label}`;
  const utilisation =
    budgetSummary.utilisation_pct != null
      ? cfoN1(parseApiAmount(budgetSummary.utilisation_pct))
      : "—";

  return (
    <>
      <SectionHead title="Budget, concentration & risk" hint={hint} />
      <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <PanelCard
          title={`Budget vs actual vs committed — ${budgetTitle}`}
          meta={`${data.meta.period_label} · ${data.meta.currency}`}
          flushBody
          foot={
            data.departments.length > 0 ? (
              <>
                <span>
                  Budget total{" "}
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
                  Utilised <strong className="text-foreground">{utilisation}%</strong>
                </span>
              </>
            ) : undefined
          }
        >
          <BudgetChart departments={data.departments} />
        </PanelCard>
        <PanelCard
          title="Vendor concentration"
          meta={top10Pct !== "—" ? `Top 10 = ${top10Pct}% of spend` : "No vendor spend in period"}
          flushBody
          foot={
            <>
              <span>
                Non-PO spend <strong className="tnum text-foreground">{nonPoPct}%</strong>
              </span>
              <span>
                Contracted vendors{" "}
                <strong className="text-foreground">
                  {summary.contracted_in_top10} of {Math.min(data.vendors.length, 10)}
                </strong>
              </span>
              <span>
                {data.vendors.length > 0
                  ? summary.high_risk_count === 1
                    ? "1 vendor flagged high risk"
                    : `${summary.high_risk_count} vendors flagged high risk`
                  : "No vendor spend"}
              </span>
            </>
          }
        >
          <ParetoChart vendors={data.vendors} />
        </PanelCard>
      </div>

      <div className="grid gap-4 mt-4">
        <PanelCard title="Budget vs actual vs committed (encumbrance)" meta="RAG on actual vs budget" flushBody>
          <DeptTable departments={data.departments} />
        </PanelCard>
        <PanelCard title="Top vendors" meta="Spend YTD · cycle time · PO coverage" flushBody>
          <VendorTable vendors={data.vendors} />
        </PanelCard>
      </div>
    </>
  );
}

export function CfoCommandCentre({ tenantName }: { tenantName?: string }) {
  const { data: liquidity } = usePositionLiquidity();
  const { data: efficiency } = useEfficiencyAutomation();

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
    return `FY activity to ${meta.period_end}${env ? ` · ${env}` : ""}`;
  }, [efficiency?.meta, tenantName]);

  return (
    <div data-testid="cfo-command-centre">
      <SectionHead
        title="Position & liquidity"
        hint={positionHint}
      />
      <PrimaryKpis />

      <SectionHead title="Efficiency & automation value" hint={efficiencyHint} />
      <SecondaryKpis />

      <CashLiabilityOutlookSection tenantName={tenantName} />

      <BudgetConcentrationRiskSection tenantName={tenantName} />

      <SectionHead title="Trends & alerts" demo />
      <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <PanelCard title="DPO & touchless trend" meta="Rolling 12 months" flushBody>
          <TrendChart />
        </PanelCard>
        <PanelCard className="h-full" title="Alerts & threshold breaches" meta="8 active · engine thresholds applied" flushBody>
          <AlertsList />
        </PanelCard>
      </div>
    </div>
  );
}

const PERIOD_OPTIONS = [
  { value: "ytd", label: "FY26 YTD (to 31 Aug 26)" },
  { value: "mtd", label: "August 2026 (MTD)" },
  { value: "q1", label: "Q1 FY26" },
  { value: "r12", label: "Rolling 12 months" },
];

const ENTITY_OPTIONS = [
  { value: "all", label: "Consolidated — all entities" },
  { value: "spectra", label: "Spectra Innovations Pty Ltd" },
  { value: "nz", label: "Spectra Logistics NZ Ltd" },
  { value: "trust", label: "Spectra Property Trust" },
];

const DEPT_OPTIONS = [
  { value: "all", label: "All departments" },
  { value: "ops", label: "Operations" },
  { value: "tech", label: "Technology" },
  { value: "sales", label: "Sales & Marketing" },
  { value: "log", label: "Logistics" },
  { value: "corp", label: "Corporate & Admin" },
  { value: "people", label: "People & Culture" },
];

const CUR_OPTIONS = [
  { value: "AUD", label: "AUD" },
  { value: "NZD", label: "NZD" },
  { value: "USD", label: "USD" },
];

export function CfoDashboardFilters() {
  const [period, setPeriod] = useState("ytd");
  const [entity, setEntity] = useState("all");
  const [dept, setDept] = useState("all");
  const [cur, setCur] = useState("AUD");

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={period} onValueChange={setPeriod} options={PERIOD_OPTIONS} data-testid="select-cfo-period" />
      <Select value={entity} onValueChange={setEntity} options={ENTITY_OPTIONS} data-testid="select-cfo-entity" />
      <Select value={dept} onValueChange={setDept} options={DEPT_OPTIONS} data-testid="select-cfo-dept" />
      <Select value={cur} onValueChange={setCur} options={CUR_OPTIONS} data-testid="select-cfo-currency" />
      <StatusPill className={pillTones.amber} title="Prototype populated with demo data">
        Demo data
      </StatusPill>
    </div>
  );
}
