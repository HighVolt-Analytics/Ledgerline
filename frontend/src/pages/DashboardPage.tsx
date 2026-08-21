import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Buildings,
  CurrencyCircleDollar,
  Gauge,
  SealCheck,
} from "@phosphor-icons/react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CaptureSourceBars, type CaptureSourceRow } from "@/components/dashboard/CaptureSourceBars";
import {
  AttentionStrip,
  type AttentionMetric,
  type AttentionPriority,
} from "@/components/dashboard/AttentionStrip";
import {
  ExecutiveKpiRow,
  type ExecutiveKpisView,
} from "@/components/dashboard/ExecutiveKpiRow";
import {
  OperationsLayer,
  type OpsMemberSnapshot,
  type OpsStatusKey,
} from "@/components/dashboard/OperationsLayer";
import { QualityApprovalRow } from "@/components/dashboard/QualityApprovalRow";
import {
  RiskCompliancePanel,
  PLACEHOLDER_RISK_ROWS,
  type RiskComplianceRow,
} from "@/components/dashboard/RiskCompliancePanel";
import {
  UserLayerChart,
  PLACEHOLDER_USER_LAYER,
  type UserLayerMetric,
  type UserLayerMetricId,
} from "@/components/dashboard/UserLayerChart";
import { ChartTooltip } from "@/components/ChartTooltip";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useDashboardOverview } from "@/hooks/useDashboardOverview";
import { useTenantTime } from "@/hooks/useTenantTime";
import { axisMoney, currencySymbol, money, toNumber } from "@/lib/format";
import type { KpiModuleColor } from "@/lib/kpiModuleColors";
import {
  buildMonthsForYear,
  buildReconYears,
  yearFromPeriod,
} from "@/lib/reconciliation";
import { defaultReportPeriod } from "@/lib/reportsData";
import { API_PORT_HINT, formatTenantLoadError } from "@/lib/tenantSession";
import type {
  CaptureSourceApiRow,
  DashboardOverview,
  ExecutiveKpiDelta,
  OpsMemberSnapshotApi,
  RiskComplianceApiRow,
  UserLayerMetricApi,
} from "@/api/types";

const CHART_MARGIN = { top: 4, right: 4, left: -18, bottom: 0 };

const CAPTURE_COLORS: Record<CaptureSourceRow["id"], KpiModuleColor> = {
  email: "blue",
  whatsapp: "violet",
  viber: "rose",
  upload: "rust",
};

const RISK_TONES: Record<string, KpiModuleColor> = {
  duplicates: "rust",
  fraud: "rose",
  bank: "violet",
  counterparties: "green",
};

const USER_LAYER_TONES: Record<UserLayerMetricId, KpiModuleColor> = {
  email_mapped: "blue",
  phone_synced: "violet",
  doc_types: "green",
  manual_handoff: "rust",
  vendors: "rose",
};

function forecastBarFill(index: number): string {
  return `hsl(186 ${64 - index * 8}% ${34 + index * 6}%)`;
}

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] || fullName;
}

function mapDelta(
  delta: ExecutiveKpiDelta | null | undefined
): ExecutiveKpisView["documentsDelta"] {
  if (!delta) return undefined;
  const dir = delta.direction === "down" ? "down" : delta.direction === "flat" ? "flat" : "up";
  return {
    dir,
    text: delta.text,
    good: delta.favorable ?? dir !== "down",
  };
}

function mapExecutiveKpis(overview: DashboardOverview): ExecutiveKpisView {
  const k = overview.executive_kpis;
  if (!k) {
    return {
      documentsProcessed: overview.stats.invoices_this_month,
      documentsDelta: undefined,
      timeSavedMinutes: 0,
      timeSavedHoursLabel: "0.0 hours recovered",
      avgTimeSavedPerDoc: 0,
      aiSavingsPct: 0,
      aiSavingsDelta: undefined,
      costSaved: 0,
    };
  }
  return {
    documentsProcessed: k.documents_processed,
    documentsDelta: mapDelta(k.documents_delta),
    timeSavedMinutes: k.time_saved_minutes,
    timeSavedHoursLabel: k.time_saved_hours_label,
    avgTimeSavedPerDoc: k.avg_time_saved_per_doc_minutes,
    aiSavingsPct: k.automation_efficiency_pct,
    aiSavingsDelta: mapDelta(k.automation_delta),
    costSaved: k.cost_saved,
  };
}

function mapCaptureSources(rows: CaptureSourceApiRow[] | undefined): CaptureSourceRow[] {
  if (!rows?.length) return [];
  return rows.map((row) => ({
    id: row.id,
    label: row.label,
    documentCount: row.document_count,
    avgTimeSavedMinutes: row.avg_time_saved_minutes,
    timeSavedMinutes: row.time_saved_minutes,
    manualMinutes: row.manual_minutes,
    costSaved: row.cost_saved,
    moduleColor: CAPTURE_COLORS[row.id],
    href: row.href,
  }));
}

function mapRiskRows(rows: RiskComplianceApiRow[] | undefined): RiskComplianceRow[] {
  if (!rows?.length) return PLACEHOLDER_RISK_ROWS;
  return rows.map((row) => ({
    id: row.id,
    label: row.label,
    count: row.count,
    href: row.href,
    badge: row.badge,
    tone: RISK_TONES[row.id] ?? "cyan",
  }));
}

function mapAttention(overview: DashboardOverview): {
  priority: AttentionPriority;
  processed: AttentionMetric;
  turnaround: AttentionMetric;
} | null {
  const a = overview.attention;
  if (!a) return null;
  return {
    priority: {
      title: a.priority.title,
      body: a.priority.body,
      ctaLabel: a.priority.cta_label,
      ctaHref: a.priority.cta_href,
    },
    processed: {
      label: a.processed.label,
      value: a.processed.value,
      deltaText: a.processed.delta_text,
      deltaGood: a.processed.delta_good,
      bars: a.processed.bars,
      icon: SealCheck,
      moduleColor: "cyan",
    },
    turnaround: {
      label: a.turnaround.label,
      value: a.turnaround.value,
      deltaText: a.turnaround.delta_text,
      deltaDown: a.turnaround.delta_down,
      deltaGood: a.turnaround.delta_good,
      bars: a.turnaround.bars,
      icon: Gauge,
      moduleColor: "rose",
    },
  };
}

function mapOpsMember(row: OpsMemberSnapshotApi): OpsMemberSnapshot {
  return {
    id: row.id,
    label: row.label,
    documentsProcessed: row.documents_processed,
    timeSavedMinutes: row.time_saved_minutes,
    automationRatePct: row.automation_rate_pct,
    pendingActions: row.pending_actions,
    accuracyPct: row.accuracy_pct,
    byDocType: row.by_doc_type.map((dt) => ({
      id: dt.id,
      label: dt.label,
      counts: {
        processed: dt.counts.processed ?? 0,
        posted: dt.counts.posted ?? 0,
        rejected: dt.counts.rejected ?? 0,
        review_pending: dt.counts.review_pending ?? 0,
        approvals_pending: dt.counts.approvals_pending ?? 0,
      } satisfies Record<OpsStatusKey, number>,
    })),
  };
}

function mapOpsWindows(
  overview: DashboardOverview
): Record<string, OpsMemberSnapshot[]> | undefined {
  const windows = overview.operations?.windows;
  if (!windows) return undefined;
  const out: Record<string, OpsMemberSnapshot[]> = {};
  for (const [key, members] of Object.entries(windows)) {
    out[key] = members.map(mapOpsMember);
  }
  return out;
}

function mapUserLayer(rows: UserLayerMetricApi[] | undefined): UserLayerMetric[] {
  if (!rows?.length) return PLACEHOLDER_USER_LAYER;
  return rows.map((row) => {
    const id = row.id as UserLayerMetricId;
    return {
      id,
      label: row.label,
      tone: USER_LAYER_TONES[id] ?? "cyan",
      stages: {
        document_fetched: row.stages.document_fetched,
        pending_confirmation: row.stages.pending_confirmation,
        pending_approval: row.stages.pending_approval,
        pending_posting: row.stages.pending_posting,
        pending_payment: row.stages.pending_payment,
      },
    };
  });
}

function dashboardSubtitle(user: { is_support_session?: boolean; tenant_name: string }) {
  if (user.is_support_session) {
    return `Support view for ${user.tenant_name}. Overview of document volume, processing, and cash forecast.`;
  }
  return "Overview of document volume, processing, and cash forecast.";
}

function DashboardWelcomeCard({
  user,
}: {
  user: {
    is_support_session?: boolean;
    tenant_name: string;
    full_name: string;
  };
}) {
  return (
    <Card
      className="px-4 py-2.5 mb-4 border-border/55 shadow-none"
      data-testid="text-welcome"
    >
      <h2 className="text-base font-semibold tracking-tight truncate">
        {user.is_support_session
          ? `Support view — ${user.tenant_name}`
          : `Welcome back, ${firstName(user.full_name)} — ${user.tenant_name}`}
      </h2>
    </Card>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const { timeZone, locale } = useTenantTime();
  const [periodOverride, setPeriodOverride] = useState<string | null>(null);
  const [riskView, setRiskView] = useState<"list" | "donut">("list");
  const period = periodOverride ?? defaultReportPeriod(timeZone);
  const setPeriod = setPeriodOverride;
  const {
    data: overview,
    error,
    isPending,
    blocked: overviewBlocked,
  } = useDashboardOverview(period, 10);

  const yearOptions = useMemo(() => buildReconYears(null, timeZone), [timeZone]);
  const selectedYear = period ? yearFromPeriod(period) : yearOptions[0] ?? "";
  const monthOptions = useMemo(
    () => (selectedYear ? buildMonthsForYear(selectedYear, timeZone, locale) : []),
    [selectedYear, timeZone, locale]
  );

  const handleYearChange = (year: string) => {
    const months = buildMonthsForYear(year, timeZone, locale);
    if (months.length === 0) {
      setPeriod("");
      return;
    }
    const monthPart = period.slice(5, 7);
    const keepMonth = months.find((m) => m.value.endsWith(`-${monthPart}`));
    setPeriod((keepMonth ?? months[0]).value);
  };

  const handleMonthChange = (monthKey: string) => {
    setPeriod(monthKey);
  };

  const periodSelector = (
    <YearMonthPeriodPicker
      year={selectedYear}
      monthKey={period}
      yearOptions={yearOptions}
      monthOptions={monthOptions}
      onYearChange={handleYearChange}
      onMonthChange={handleMonthChange}
      disabled={isPending && !overview}
      yearId="dashboard-year"
      monthId="dashboard-month"
      yearTestId="select-dashboard-year"
      monthTestId="select-dashboard-month"
      pickerTestId="dashboard-period-picker"
    />
  );

  if (error && !overviewBlocked) {
    const message =
      error instanceof Error ? error.message : "Failed to load dashboard";
    return (
      <div>
        {user && (
          <PageHeader title="Dashboard" subtitle={dashboardSubtitle(user)} actions={periodSelector} />
        )}
        <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
          {formatTenantLoadError(message, API_PORT_HINT)}
        </Card>
      </div>
    );
  }

  if (overviewBlocked || !user || (isPending && !overview)) {
    return (
      <div>
        {user ? (
          <PageHeader title="Dashboard" subtitle={dashboardSubtitle(user)} actions={periodSelector} />
        ) : (
          <PageHeader
            title="Dashboard"
            subtitle="Overview of document volume, processing, and cash forecast."
          />
        )}
        <PageLoader variant="dashboard" />
      </div>
    );
  }

  if (!overview) {
    return (
      <div>
        <PageHeader title="Dashboard" subtitle={dashboardSubtitle(user)} actions={periodSelector} />
        <PageLoader variant="dashboard" />
      </div>
    );
  }

  const { stats, top_vendors, cash_forecast } = overview;
  const baseCurrency = stats.base_currency || "";
  const fmt = (v: string | number | null | undefined) => money(v, baseCurrency, locale);
  const currencySym = currencySymbol(baseCurrency);
  const executiveKpis = mapExecutiveKpis(overview);
  const captureRows = mapCaptureSources(overview.capture_sources);
  const riskRows = mapRiskRows(overview.risk_compliance);
  const attention = mapAttention(overview);
  const opsWindows = mapOpsWindows(overview);
  const extractionPoints = (overview.extraction_quality ?? []).map((p) => ({
    metric: p.metric,
    accuracy: p.accuracy,
  }));
  const approvalStats = overview.approval_queue
    ? {
        pending: overview.approval_queue.pending,
        valueLabel: overview.approval_queue.value_label,
        medianTimeLabel: overview.approval_queue.median_time_label,
      }
    : undefined;
  const userLayer = mapUserLayer(overview.user_layer);

  if (stats.total_invoices === 0) {
    return (
      <div>
        <PageHeader
          title="Dashboard"
          subtitle={dashboardSubtitle(user)}
          actions={periodSelector}
        />
        <DashboardWelcomeCard user={user} />
        <Card className="p-8 flex flex-col items-center text-center max-w-lg mx-auto">
          <h3 className="text-sm font-semibold mb-2">No documents loaded yet</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Connect a mailbox or upload invoices to populate your dashboard.
          </p>
          <Link
            to="/upload"
            data-testid="button-load-samples"
            className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Go to Upload
          </Link>
        </Card>
      </div>
    );
  }

  const forecastData = cash_forecast.map((b) => ({
    label: b.label,
    amount: toNumber(b.amount),
  }));
  const forecastTotal = forecastData.reduce((sum, row) => sum + row.amount, 0);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={dashboardSubtitle(user)}
        actions={periodSelector}
      />

      <DashboardWelcomeCard user={user} />

      <ExecutiveKpiRow currencySymbol={currencySym} kpis={executiveKpis} />

      <div className="grid gap-4 lg:grid-cols-3 lg:items-stretch mb-6">
        <CaptureSourceBars
          className="lg:col-span-2"
          expand={riskView === "donut"}
          rows={captureRows.length ? captureRows : undefined}
        />
        <RiskCompliancePanel
          view={riskView}
          onViewChange={setRiskView}
          rows={riskRows}
        />
      </div>

      <AttentionStrip
        priority={attention?.priority}
        processed={attention?.processed}
        turnaround={attention?.turnaround}
      />

      <OperationsLayer windows={opsWindows} />

      <QualityApprovalRow
        extraction={extractionPoints.length ? extractionPoints : undefined}
        approval={approvalStats}
      />

      <UserLayerChart metrics={userLayer} />

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <Card className="p-4 lg:col-span-2 dash-card--elevated">
          <h3 className="text-sm font-semibold mb-1 inline-flex items-center gap-2">
            <CurrencyCircleDollar size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
            Cash-out forecast
          </h3>
          <p className="text-xs text-muted-foreground mb-3">
            {overview.cash_forecast_scope}
          </p>
          {forecastTotal <= 0 ? (
            <p className="text-sm text-muted-foreground h-40 flex items-center">
              No upcoming payables with due dates. Processed and open invoices appear here
              once they have a due date and amount.
            </p>
          ) : (
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={forecastData} margin={CHART_MARGIN}>
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10 }}
                    stroke="hsl(var(--muted-foreground))"
                  />
                  <YAxis
                    tick={{ fontSize: 10 }}
                    stroke="hsl(var(--muted-foreground))"
                    tickFormatter={(v) => axisMoney(v, currencySym)}
                  />
                  <Tooltip
                    cursor
                    content={({ active, payload, label }) => (
                      <ChartTooltip
                        active={active}
                        payload={payload}
                        label={label}
                        valueFormatter={(v) => fmt(v)}
                      />
                    )}
                  />
                  <Bar dataKey="amount" radius={[4, 4, 0, 0]}>
                    {forecastData.map((row, i) => (
                      <Cell key={row.label} fill={forecastBarFill(i)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card className="p-4 dash-card--elevated">
          <h3 className="text-sm font-semibold mb-3 inline-flex items-center gap-2">
            <Buildings size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
            Top vendors
          </h3>
          {top_vendors.length === 0 ? (
            <p className="text-sm text-muted-foreground">No vendor data for this period.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-1.5 font-medium">#</th>
                  <th className="py-1.5 font-medium">Vendor</th>
                  <th className="py-1.5 font-medium text-right">Docs</th>
                  <th className="py-1.5 font-medium text-right">Value</th>
                </tr>
              </thead>
              <tbody>
                {top_vendors.map((x, g) => (
                  <tr key={x.vendor} className="row-band border-t border-border/60">
                    <td className="py-1.5 tnum text-muted-foreground">{g + 1}</td>
                    <td className="py-1.5 truncate max-w-[160px]">{x.vendor}</td>
                    <td className="py-1.5 text-right tnum">{x.invoice_count}</td>
                    <td className="py-1.5 text-right tnum">{fmt(x.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

    </div>
  );
}
