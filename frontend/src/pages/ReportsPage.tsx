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
import { EmptyState } from "@/components/EmptyState";
import { ChartTooltip } from "@/components/ChartTooltip";
import { SubledgerBalanceTable } from "@/components/reports/SubledgerBalanceTable";
import { ReportDownloadMenu } from "@/components/reports/ReportDownloadMenu";
import { TeamExpenseReportsSection } from "@/components/reports/TeamExpenseReportsSection";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Card } from "@/components/ui/card";
import { useTenantTime } from "@/hooks/useTenantTime";
import { useReportsAnalytics } from "@/hooks/useReportsAnalytics";
import { useApBalances, useArBalances } from "@/hooks/useSubledgerBalances";
import { axisMoney, currencySymbol, money, toNumber } from "@/lib/format";
import {
  REPORT_CHART_COLORS,
  defaultReportPeriod,
  mapGlAccountRow,
  mapVendorSpendRow,
} from "@/lib/reportsData";
import { tenantTodayIso } from "@/lib/tenantTime";

const REPORTS_SUBTITLE =
  "Spend analytics, party balances, and team expense finance (advances + GL budgets).";

const CHART_MARGIN = { top: 4, right: 12, left: 8, bottom: 0 };
const PIE_HOVER_OFFSET = 6;
const SUSPENSE_ACCOUNT_COLOR = "hsl(var(--cyan-500))";

function reportAccountColor(account: string, index: number): string {
  if (account.toLowerCase().includes("suspense")) return SUSPENSE_ACCOUNT_COLOR;
  return REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length]!;
}

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
      stroke="none"
    />
  );
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
  const { timeZone, locale } = useTenantTime();
  const month = defaultReportPeriod(timeZone);
  const [toast, setToast] = useState<string | null>(null);
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
  const [activePieIndex, setActivePieIndex] = useState<number | null>(null);

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 3500);
  };

  const { data: analytics, isLoading, error } = useReportsAnalytics(month);
  const subledgerAsOf = tenantTodayIso(timeZone);
  const { data: apBalances, isLoading: apLoading } = useApBalances(subledgerAsOf);
  const { data: arBalances, isLoading: arLoading } = useArBalances(subledgerAsOf);

  const currency = analytics?.base_currency ?? "";
  const taxLabel = analytics?.tax_label ?? "Tax";
  const symbol = currencySymbol(currency);
  const fmt = (v: number) => money(v, currency, locale);

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

  const headerActions = (
    <ReportDownloadMenu
      month={month}
      analytics={analytics}
      disabled={isLoading}
      onToast={showToast}
    />
  );

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Reports" subtitle={REPORTS_SUBTITLE} />
        <PageLoader variant="reports" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader title="Reports" subtitle={REPORTS_SUBTITLE} />
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
          subtitle={REPORTS_SUBTITLE}
          actions={headerActions}
        />
        {toast && (
          <Card className="p-3 mb-4 text-sm border-primary/30 bg-primary/5">{toast}</Card>
        )}
        <EmptyState
          title="No processed invoices this month"
          hint="Spend charts include processed invoices only. Team expense balances below still update from employee advances and claims."
        />
        <TeamExpenseReportsSection month={month} currency={currency} locale={locale} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Reports"
        subtitle={REPORTS_SUBTITLE}
        actions={headerActions}
      />

      {toast && (
        <Card className="p-3 mb-4 text-sm border-primary/30 bg-primary/5">{toast}</Card>
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
                        fill={reportAccountColor(row.account, index)}
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
                    stroke="none"
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
                        fill={reportAccountColor(row.account, index)}
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
                <th className="py-1.5 font-medium">GL Account</th>
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

      <Card className="p-4">
        <h2 className="text-base font-semibold mb-1">AP / AR party balances</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Open balances by vendor under the Rule Book payable ledger, and by customer under the
          receivable ledger. (Rule Book expense “Sub-ledger” fields are GL coding segments, not
          these party balances.)
        </p>
        <div className="grid gap-4 sm:grid-cols-2 mb-4">
          <KpiCard
            label="Total AP outstanding"
            value={
              apLoading
                ? "…"
                : fmt(toNumber(apBalances?.totals.balance ?? 0))
            }
            delta={{
              dir: "flat",
              text: `${apBalances?.totals.counterparty_count ?? 0} vendors`,
            }}
          />
          <KpiCard
            label="Total AR outstanding"
            value={
              arLoading
                ? "…"
                : fmt(toNumber(arBalances?.totals.balance ?? 0))
            }
            delta={{
              dir: "flat",
              text: `${arBalances?.totals.counterparty_count ?? 0} customers`,
            }}
          />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <SubledgerBalanceTable
            title="AP vendor balances"
            data={apBalances}
            currency={apBalances?.base_currency ?? currency}
            emptyLabel="No open AP balances"
            unregisteredLabel="Unregistered vendors"
          />
          <SubledgerBalanceTable
            title="AR customer balances"
            data={arBalances}
            currency={arBalances?.base_currency ?? currency}
            emptyLabel="No open AR balances"
            unregisteredLabel="Unregistered customers"
          />
        </div>
      </Card>

      <TeamExpenseReportsSection month={month} currency={currency} locale={locale} />
    </div>
  );
}
