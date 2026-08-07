import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Buildings,
  CurrencyCircleDollar,
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
import { CaptureSourceBars } from "@/components/dashboard/CaptureSourceBars";
import { AttentionStrip } from "@/components/dashboard/AttentionStrip";
import { ExecutiveKpiRow } from "@/components/dashboard/ExecutiveKpiRow";
import { OperationsLayer } from "@/components/dashboard/OperationsLayer";
import { QualityApprovalRow } from "@/components/dashboard/QualityApprovalRow";
import { RecentActivityCard } from "@/components/dashboard/RecentActivityCard";
import { RiskCompliancePanel } from "@/components/dashboard/RiskCompliancePanel";
import { UserLayerChart } from "@/components/dashboard/UserLayerChart";
import { ChartTooltip } from "@/components/ChartTooltip";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useDashboardOverview } from "@/hooks/useDashboardOverview";
import { useTenantTime } from "@/hooks/useTenantTime";
import { axisMoney, currencySymbol, money, toNumber } from "@/lib/format";
import {
  buildMonthsForYear,
  buildReconYears,
  yearFromPeriod,
} from "@/lib/reconciliation";
import { defaultReportPeriod } from "@/lib/reportsData";
import { API_PORT_HINT, formatTenantLoadError } from "@/lib/tenantSession";

const CHART_MARGIN = { top: 4, right: 4, left: -18, bottom: 0 };

function forecastBarFill(index: number): string {
  return `hsl(186 ${64 - index * 8}% ${34 + index * 6}%)`;
}

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] || fullName;
}

function relativePollTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
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
    isLoading,
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
      disabled={isLoading}
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

  if (isLoading || overviewBlocked || !overview || !user) {
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

  const { stats, top_vendors, cash_forecast, activity } = overview;
  const baseCurrency = stats.base_currency || "SGD";
  const fmt = (v: string | number | null | undefined) => money(v, baseCurrency, locale);
  const currencySym = currencySymbol(baseCurrency);

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

  const activityFeed = activity.slice(0, 10).map((a) => ({
    id: String(a.id),
    invoiceId: a.invoice_id,
    event: a.event,
    documentRef: a.document_ref ?? (a.invoice_id != null ? `DOC-${a.invoice_id}` : null),
    vendor: a.vendor,
    summary: a.summary ?? null,
    time: relativePollTime(a.created_at),
  }));

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={dashboardSubtitle(user)}
        actions={periodSelector}
      />

      <DashboardWelcomeCard user={user} />

      <ExecutiveKpiRow currencySymbol={currencySym} />

      <div className="grid gap-4 lg:grid-cols-3 lg:items-stretch mb-6">
        <CaptureSourceBars className="lg:col-span-2" expand={riskView === "donut"} />
        <RiskCompliancePanel view={riskView} onViewChange={setRiskView} />
      </div>

      <AttentionStrip />

      <OperationsLayer />

      <QualityApprovalRow />

      <UserLayerChart />

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

      <RecentActivityCard items={activityFeed} />
    </div>
  );
}
