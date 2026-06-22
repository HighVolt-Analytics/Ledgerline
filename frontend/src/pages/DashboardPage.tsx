import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Mail } from "lucide-react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { KpiSparklines, KpiTrend } from "@/api/types";
import { KpiCard } from "@/components/KpiCard";
import { ChartTooltip } from "@/components/ChartTooltip";
import { PageLoader } from "@/components/PageLoader";
import { YearMonthPeriodPicker } from "@/components/YearMonthPeriodPicker";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useDashboardOverview } from "@/hooks/useDashboardOverview";
import { axisMoney, currencySymbol, formatDuration, money, toNumber } from "@/lib/format";
import { toV3SparkSeries } from "@/lib/kpiSpark";
import { vaultInvoiceLink } from "@/lib/vault";
import {
  buildMonthsForYear,
  buildReconYears,
  formatReconMonthLabel,
  yearFromPeriod,
} from "@/lib/reconciliation";
import { defaultReportPeriod } from "@/lib/reportsData";
import { cn } from "@/lib/cn";

const CHART_MARGIN = { top: 4, right: 4, left: -18, bottom: 0 };
const EMAIL_BAR_FILL = "hsl(186 64% 34%)";

function forecastBarFill(index: number): string {
  return `hsl(186 ${64 - index * 8}% ${34 + index * 6}%)`;
}

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] || fullName;
}

function formatSecondsShort(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return formatDuration(seconds);
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

function anomalyBadgeClass(tag: string) {
  if (tag === "Duplicate") return "border-destructive/40 text-destructive text-[10px]";
  if (tag === "Missing PO" || tag === "Pending vendor" || tag === "Needs review") {
    return "border-[hsl(43_74%_49%/0.5)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)] text-[10px]";
  }
  if (tag === "GST mismatch" || tag === "Team policy" || tag === "Validation") {
    return "border-destructive/30 text-destructive text-[10px]";
  }
  return "text-muted-foreground text-[10px]";
}

function mailboxNickname(email: string, displayName: string | null): string {
  const label = displayName?.trim();
  if (label && !label.includes("@")) return label;
  const local = email.split("@")[0] ?? "Mailbox";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

function activityLabel(
  event: string,
  vendor: string | null,
  invoiceId: number | null,
  summary?: string | null
): string {
  const id = invoiceId != null ? `INV-${String(invoiceId).padStart(3, "0")}` : "System";
  const who = vendor ?? "Unknown vendor";
  let label = `${id} · ${who}`;

  if (summary?.trim()) {
    return `${label} — ${summary.trim()}`;
  }
  if (event === "duplicate_skipped") {
    return `${label} duplicate skipped`;
  }
  if (event === "duplicate_in_progress") {
    return `${label} duplicate blocked (still processing)`;
  }
  if (event === "duplicate_reingest_rejected") {
    return `${label} resubmitted after rejection`;
  }
  if (event.includes("validation_failed") || event.includes("parsing_failed")) {
    return `${label} validation failed`;
  }
  if (event.includes("processed")) {
    return `${label} published to ledger`;
  }
  if (event.includes("approved")) {
    return `${label} approved for reprocessing`;
  }
  if (event.includes("upload")) {
    return `${label} captured via upload`;
  }
  if (event.includes("email") || event.includes("ingest") || event.includes("poll")) {
    return `${label} captured via email`;
  }
  return `${label} — ${event.replace(/_/g, " ")}`;
}

function trendToDelta(trend: KpiTrend | undefined) {
  if (!trend) return undefined;
  return {
    dir: trend.direction,
    text: trend.text,
    good: trend.favorable ?? undefined,
  };
}

export function DashboardPage() {
  const { user } = useAuth();
  const [period, setPeriod] = useState(() => defaultReportPeriod());
  const {
    data: overview,
    error,
    isLoading,
  } = useDashboardOverview(period, 10);

  const yearOptions = useMemo(() => buildReconYears(null), []);
  const selectedYear = period ? yearFromPeriod(period) : yearOptions[0] ?? "";
  const monthOptions = useMemo(
    () => (selectedYear ? buildMonthsForYear(selectedYear) : []),
    [selectedYear]
  );

  const handleYearChange = (year: string) => {
    const months = buildMonthsForYear(year);
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

  const periodLabel = formatReconMonthLabel(period) || period;

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

  if (error) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error instanceof Error ? error.message : "Failed to load dashboard"}. Ensure the API is
        running on port 8001.
      </Card>
    );
  }

  if (isLoading || !overview) {
    return <PageLoader label="Loading dashboard…" />;
  }

  if (!user) {
    return <PageLoader label="Loading dashboard…" />;
  }

  const {
    stats,
    top_vendors,
    cash_forecast,
    invoice_volume_sparkline,
    mailbox_breakdown,
    anomalies,
    kpi_trends,
    kpi_sparklines,
    activity,
    period_has_data,
  } = overview;
  const baseCurrency = stats.base_currency || "AUD";
  const fmt = (v: string | number | null | undefined) => money(v, baseCurrency);
  const sparks: KpiSparklines = kpi_sparklines ?? {
    invoice_volume: invoice_volume_sparkline,
    docs_via_email: [],
    docs_via_upload: [],
    total_value: [],
    distinct_vendors: [],
    mailboxes_active: [],
    active_users: [],
    avg_processing_seconds: [],
    reconciliation_delta: [],
  };

  if (stats.total_invoices === 0) {
    return (
      <div>
        <Card
          className="p-5 mb-6 bg-gradient-to-r from-primary/5 to-transparent border-primary/15"
          data-testid="text-welcome"
        >
          <h1 className="text-xl font-semibold tracking-tight">
            Welcome back, {firstName(user.full_name)} — {user.tenant_name}
          </h1>
          <Badge variant="outline" className="mt-2 text-xs font-normal text-muted-foreground tnum" data-testid="chip-userid">
            {user.email}
          </Badge>
        </Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold">Overview</h2>
          {periodSelector}
        </div>
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

  const reconDeltaText =
    stats.reconciliation_delta_dr_cr != null
      ? fmt(stats.reconciliation_delta_dr_cr)
      : fmt(0);

  const reconLabel =
    stats.last_reconciliation_balanced == null
      ? "—"
      : stats.last_reconciliation_balanced
        ? "Balanced"
        : "Out of balance";

  const mailboxActivity =
    sparks.mailboxes_active.length > 0
      ? sparks.mailboxes_active[sparks.mailboxes_active.length - 1]
      : 0;

  const row1 = [
    {
      label: "Active users",
      value: stats.active_users,
      delta: trendToDelta(kpi_trends.active_users),
      spark: toV3SparkSeries(sparks.active_users, stats.active_users, "count"),
      testid: "kpi-active-users",
    },
    {
      label: "Mailboxes mapped",
      value: stats.mailboxes_mapped,
      delta: trendToDelta(kpi_trends.mailboxes_active),
      spark: toV3SparkSeries(sparks.mailboxes_active, mailboxActivity, "count"),
      testid: "kpi-mailboxes-mapped",
    },
    {
      label: "Docs via email",
      value: stats.docs_via_email,
      delta: trendToDelta(kpi_trends.docs_via_email),
      spark: toV3SparkSeries(sparks.docs_via_email, stats.docs_via_email, "count"),
      testid: "kpi-docs-email",
    },
    {
      label: "Docs via upload",
      value: stats.docs_via_upload,
      delta: trendToDelta(kpi_trends.docs_via_upload),
      spark: toV3SparkSeries(sparks.docs_via_upload, stats.docs_via_upload, "count"),
      testid: "kpi-docs-upload",
    },
  ];

  const row2 = [
    {
      label: "Avg processing time",
      value: formatSecondsShort(stats.avg_processing_seconds),
      delta: trendToDelta(kpi_trends.avg_processing_seconds),
      spark: toV3SparkSeries(
        sparks.avg_processing_seconds,
        stats.avg_processing_seconds ?? 0,
        "seconds",
      ),
      testid: "kpi-avg-processing",
    },
    {
      label: "Total value",
      value: fmt(stats.total_value ?? stats.total_value_aud),
      delta: trendToDelta(kpi_trends.total_value ?? kpi_trends.total_value_aud),
      spark: toV3SparkSeries(sparks.total_value, toNumber(stats.total_value ?? stats.total_value_aud), "money"),
      testid: "kpi-total-value",
    },
    {
      label: "Distinct vendors",
      value: stats.distinct_vendors,
      delta: trendToDelta(kpi_trends.distinct_vendors),
      spark: toV3SparkSeries(sparks.distinct_vendors, stats.distinct_vendors, "count"),
      testid: "kpi-distinct-vendors",
    },
    {
      label: "Reconciliation",
      value: reconLabel,
      delta: stats.last_reconciliation_balanced != null
        ? stats.last_reconciliation_balanced
          ? {
              dir: "flat" as const,
              text: reconDeltaText,
              good: true,
            }
          : {
              dir: "up" as const,
              text: `Δ ${reconDeltaText}`,
              good: false,
            }
        : undefined,
      testid: "kpi-recon",
    },
  ];

  const forecastData = cash_forecast.map((b) => ({
    label: b.label,
    amount: toNumber(b.amount),
  }));
  const forecastTotal = forecastData.reduce((sum, row) => sum + row.amount, 0);
  const currencySym = currencySymbol(baseCurrency);

  const mailboxChartData = mailbox_breakdown.map((mb) => ({
    name: mailboxNickname(mb.email, mb.display_name),
    count: mb.document_count,
  }));

  const activityFeed = activity.slice(0, 10).map((a) => ({
    id: String(a.id),
    invoiceId: a.invoice_id,
    label: activityLabel(a.event, a.vendor, a.invoice_id, a.summary),
    time: relativePollTime(a.created_at),
  }));

  return (
    <div>
      <Card
        className="p-5 mb-6 bg-gradient-to-r from-primary/5 to-transparent border-primary/15"
      >
        <h1 className="text-xl font-semibold tracking-tight" data-testid="text-welcome">
          Welcome back, {firstName(user.full_name)} — {user.tenant_name}
        </h1>
        <Badge
          variant="outline"
          className="mt-2 text-xs font-normal text-muted-foreground tnum"
          data-testid="chip-userid"
        >
          {user.email}
        </Badge>
      </Card>

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold">Overview</h2>
        {periodSelector}
      </div>

      {!period_has_data && (
        <Card className="p-4 mb-4 border-dashed border-border bg-muted/30 text-sm text-muted-foreground">
          No documents were received in {periodLabel}. KPIs below show zeros for this period.
          Select another month or{" "}
          <Link to="/upload" className="text-primary hover:underline">
            capture new documents
          </Link>
          .
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-3">
        {row1.map((k) => (
          <KpiCard key={k.label} {...k} />
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        {row2.map((k) => (
          <KpiCard key={k.label} {...k} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <Card className="p-4 lg:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <Mail className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">Email source breakdown</h3>
          </div>
          {mailbox_breakdown.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No mailboxes connected.{" "}
              <Link to="/upload" className="text-primary hover:underline">
                Add a mailbox
              </Link>
            </p>
          ) : (
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-2">
                {mailbox_breakdown.map((mb) => (
                  <div
                    key={mb.mailbox_id}
                    className="flex items-center justify-between text-sm border-b border-border/60 pb-2"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">
                        {mailboxNickname(mb.email, mb.display_name)}
                      </div>
                      <div className="text-xs text-muted-foreground truncate tnum">{mb.email}</div>
                    </div>
                    <div className="text-right shrink-0 ml-3">
                      <div className="tnum font-medium">{mb.document_count}</div>
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px]",
                          mb.is_active
                            ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                            : "text-muted-foreground"
                        )}
                      >
                        {relativePollTime(mb.last_poll_at)}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={mailboxChartData} margin={CHART_MARGIN}>
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 10 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      stroke="hsl(var(--muted-foreground))"
                      allowDecimals={false}
                    />
                    <Tooltip
                      cursor
                      content={({ active, payload, label }) => (
                        <ChartTooltip active={active} payload={payload} label={label} />
                      )}
                    />
                    <Bar
                      dataKey="count"
                      fill={EMAIL_BAR_FILL}
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-1">Cash-out forecast</h3>
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
      </div>

      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">Top vendors</h3>
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

        <Card className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="h-4 w-4 text-[hsl(43_74%_49%)]" />
            <h3 className="text-sm font-semibold">Anomalies</h3>
          </div>
          {anomalies.length === 0 ? (
            <p className="text-sm text-muted-foreground">No anomalies detected.</p>
          ) : (
            <div className="space-y-2">
              {anomalies.map((a, i) => (
                <div
                  key={`${a.tag}-${a.invoice_id ?? i}`}
                  className="flex items-start gap-2 text-sm border-b border-border/60 pb-2"
                >
                  <Badge variant="outline" className={cn("shrink-0", anomalyBadgeClass(a.tag))}>
                    {a.tag}
                  </Badge>
                  <span className="text-xs text-muted-foreground flex-1">{a.description}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Recent activity</h3>
        </div>
        {activityFeed.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent events.</p>
        ) : (
          <ol className="space-y-2">
            {activityFeed.map((item) => (
              <li key={item.id} className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--chart-1))] shrink-0" />
                {item.invoiceId != null ? (
                  <Link
                    to={vaultInvoiceLink(item.invoiceId)}
                    className="truncate flex-1 hover:text-primary hover:underline"
                    title="Open document in Vault"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span className="truncate flex-1">{item.label}</span>
                )}
                <span className="text-xs text-muted-foreground tnum shrink-0">{item.time}</span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
