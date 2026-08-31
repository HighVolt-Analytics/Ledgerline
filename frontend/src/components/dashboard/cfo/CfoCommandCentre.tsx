import { useMemo, useState, type ReactElement, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import { CFO_DEMO } from "@/lib/cfoDemoData";
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
  KPI_MODULE_CHART_LIGHT,
} from "@/lib/kpiModuleColors";

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
  budget: { top: 4, right: 8, left: 0, bottom: 0 },
  pareto: { top: 4, right: 8, left: 0, bottom: 4 },
  trend: { top: 4, right: 8, left: 0, bottom: 0 },
  ageing: { top: 0, right: 12, left: 0, bottom: 0 },
} as const;

const AGEING_COLORS = [
  KPI_MODULE_CHART_LIGHT.blue,
  KPI_MODULE_CHART_LIGHT.violet,
  "hsl(var(--warning))",
  KPI_MODULE_CHART_LIGHT.rust,
  "hsl(var(--destructive))",
] as const;

type LegendItem = { color: string; label: string; line?: boolean; dashed?: boolean };

function cfoDeptTick(name: string) {
  if (name.includes(" & ")) {
    const [a, b] = name.split(" & ");
    return `${a} &\n${b}`;
  }
  return name;
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

function SectionHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-3 mt-8 mb-3 first:mt-0">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground m-0">
        {title}
      </h2>
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

function PrimaryKpis() {
  const K = CFO_DEMO.kpi;
  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">A$</span>
      {cfoN0(v)}
    </>
  );

  const tiles: KpiTileDef[] = [
    { label: "AP outstanding", value: cur(K.apOutstanding), foot: <>Approved not paid <strong className="tnum text-foreground">{cfoN0(K.approvedNotPaid)}</strong></> },
    { label: "Due next 7 days", value: cur(K.due7), foot: <>14 d <span className="tnum">{cfoN0(K.due14)}</span> · 30 d <span className="tnum">{cfoN0(K.due30)}</span></> },
    { label: "Overdue", value: cur(K.overdue), foot: <><span className="text-destructive font-medium tnum">{cfoPct(K.overduePct)}</span> of AP · threshold 10%</>, meter: { pct: K.overduePct * 4, tone: "neg" } },
    { label: "Days payable outstanding", value: <>{cfoN1(K.dpo)}<span className="text-base font-medium text-muted-foreground ml-1">days</span></>, foot: <><span className="text-emerald-600 dark:text-emerald-400 font-medium">▼ {cfoN1(K.dpoPrior - K.dpo)}</span> vs PY {cfoN1(K.dpoPrior)}</> },
    { label: "On-time payment rate", value: cfoPct(K.onTimeRate), foot: <>Discount capture <span className="tnum">{cfoPct(K.discountRate)}</span></>, meter: { pct: K.onTimeRate, tone: "pos" } },
    { label: "Budget utilisation", value: cfoPct(K.utilisation), foot: <>Actual <span className="tnum">{cfoCompact(K.actualYTD)}</span> of <span className="tnum">{cfoCompact(K.budgetYTD)}</span></>, meter: { pct: K.utilisation, tone: "warn" } },
    { label: "Advances outstanding", value: cur(K.advancesOutstanding), foot: <><span className="text-destructive font-medium tnum">{cfoN0(K.advancesOverdue)}</span> overdue · {K.advancesOverdueEmployees} employees</> },
    { label: "Open exceptions", value: <>{cfoN0(K.openExceptions)}<span className="text-base font-medium text-muted-foreground ml-1">items</span></>, foot: <><span className="tnum">{cfoN0(K.exceptionAtRisk)}</span> at risk</> },
    { label: "Claims pending approval", value: <>{cfoN0(K.claimsPending)}<span className="text-base font-medium text-muted-foreground ml-1">claims</span></>, foot: <><span className="tnum">{cfoN0(K.claimsPendingValue)}</span> awaiting sign-off</> },
    { label: "Vendor concentration", value: cfoPct(K.top10Concentration), foot: <>Top 10 · non-PO {cfoPct(K.nonPoSpend)}</>, meter: { pct: K.top10Concentration, tone: "warn" } },
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
  const K = CFO_DEMO.kpi;
  const cur = (v: number) => (
    <>
      <span className="text-muted-foreground text-base font-medium mr-0.5">A$</span>
      {cfoN0(v)}
    </>
  );

  const tiles: KpiTileDef[] = [
    { label: "Touchless processing", value: cfoPct(K.touchless), foot: <>Target {cfoN0(K.touchlessTarget)}%</>, meter: { pct: K.touchless, tone: "warn" } },
    { label: "Cost per invoice", value: <><span className="text-muted-foreground text-base font-medium mr-0.5">A$</span>{cfoN2(K.costPerInvoice)}</>, foot: <>Baseline <span className="tnum">{cfoN2(K.costBaseline)}</span></> },
    { label: "Avg processing time", value: <>{cfoN1(K.avgProcMins)}<span className="text-base font-medium text-muted-foreground ml-1">min</span></>, foot: <>Baseline {cfoN0(K.baselineMins)} min</> },
    { label: "Hours saved YTD", value: cfoN0(K.hoursSaved), foot: <><strong>{cfoN1(K.fte)} FTE</strong> released</> },
    { label: "Documents processed", value: cfoN0(K.invoicesYTD), foot: <>MTD <span className="tnum">{cfoN0(K.invoicesMTD)}</span></> },
    { label: "Duplicates prevented", value: cur(K.dupPrevented), foot: <>Fraud blocked <span className="tnum">{cfoN0(K.fraudAtRisk)}</span></> },
    { label: "Discount captured", value: cur(K.discountCaptured), foot: <>Available <span className="tnum">{cfoN0(K.discountAvailable)}</span></> },
    { label: "Total value delivered", value: cur(K.valueDelivered), foot: "Automation & prevention YTD" },
    { label: "Sync success", value: cfoPct(K.syncSuccess), foot: <>{K.deadLetter} dead-letter</>, meter: { pct: K.syncSuccess, tone: "pos" } },
    { label: "Documents past retention", value: cfoN0(K.pastRetention), foot: <>Missing docs <span className="tnum">{cfoN0(K.missingDocs)}</span></> },
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

function CashForecastChart() {
  const data = CFO_DEMO.cashWeeks.map((label, i) => ({
    label,
    confirmed: CFO_DEMO.cashSplit.confirmed[i],
    probable: CFO_DEMO.cashSplit.probable[i],
    recurring: CFO_DEMO.cashSplit.recurring[i],
    reimbursements: CFO_DEMO.cashSplit.reimbursements[i],
    advances: CFO_DEMO.cashSplit.advances[i],
    tax: CFO_DEMO.cashSplit.tax[i],
    balance: CFO_DEMO.cashMeta[i]?.balance ?? 0,
  }));

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.cash}
      legend={[
        ...CASH_STACK.map((s) => ({ color: s.color, label: s.label })),
        { color: CHART_INK, label: "Available balance", line: true, dashed: true },
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
        <YAxis
          yAxisId="right"
          orientation="right"
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={cfoAxisCompact}
          width={52}
        />
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
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="balance"
          name="Available balance"
          stroke={CHART_INK}
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="4 3"
        />
      </ComposedChart>
    </CfoChartBlock>
  );
}

function AgeingChart() {
  const data = CFO_DEMO.ageing.map((a) => ({ bucket: a.bucket, value: a.value }));
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

function BudgetChart() {
  const data = CFO_DEMO.departments.map((d) => ({
    name: cfoDeptTick(d.name),
    budget: d.budget,
    actual: d.actual,
    committed: d.committed,
    over: d.actual > d.budget,
  }));

  return (
    <CfoChartBlock
      height={CHART_HEIGHT.tall}
      legend={[
        { color: "hsl(var(--muted))", label: "Budget" },
        { color: KPI_MODULE_CHART_LIGHT.blue, label: "Actual" },
        { color: KPI_MODULE_CHART_LIGHT.teal, label: "Committed" },
      ]}
    >
      <ComposedChart data={data} margin={CHART_MARGIN.budget} barCategoryGap="24%" barGap={4}>
        <CartesianGrid stroke={CHART_GRID} vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10.5, fill: CHART_AXIS }}
          axisLine={{ stroke: CHART_GRID }}
          tickLine={false}
          interval={0}
          height={52}
        />
        <YAxis
          tick={{ fontSize: 10, fill: CHART_AXIS }}
          axisLine={false}
          tickLine={false}
          tickFormatter={cfoAxisCompact}
          width={52}
        />
        <Tooltip
          content={({ active, payload, label }) => (
            <ChartTooltip
              active={active}
              payload={payload}
              label={String(label).replace("\n", " ")}
              valueFormatter={(v) => cfoMoney(v)}
            />
          )}
        />
        <Bar dataKey="budget" name="Budget" fill="hsl(var(--muted))" radius={[3, 3, 0, 0]} maxBarSize={22} />
        <Bar dataKey="actual" name="Actual" radius={[3, 3, 0, 0]} maxBarSize={22}>
          {data.map((entry) => (
            <Cell key={entry.name} fill={entry.over ? "hsl(var(--destructive))" : KPI_MODULE_CHART_LIGHT.blue} />
          ))}
        </Bar>
        <Bar dataKey="committed" name="Committed" fill={KPI_MODULE_CHART_LIGHT.teal} radius={[3, 3, 0, 0]} maxBarSize={22} />
      </ComposedChart>
    </CfoChartBlock>
  );
}

function ParetoChart() {
  const totalSpend = 8840000;
  let cum = 0;
  const data = CFO_DEMO.vendors.map((v) => {
    cum += v.spend;
    return {
      name: v.name.split(" ")[0],
      fullName: v.name,
      spend: v.spend,
      cumulative: (cum / totalSpend) * 100,
      risk: v.risk,
    };
  });

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
            return (
              <div className="chart-tooltip">
                <p className="chart-tooltip-label">{row?.fullName}</p>
                {payload.map((p) => {
                  const val = Number((p as { value?: number }).value ?? 0);
                  const name = String((p as { name?: string }).name ?? "");
                  return (
                    <p key={name} className="chart-tooltip-value tnum">
                      {name.includes("Cumulative") ? cfoPct(val) : cfoMoney(val)}
                    </p>
                  );
                })}
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

function DeptTable() {
  const rows = CFO_DEMO.departments;
  const totals = rows.reduce(
    (a, d) => ({ budget: a.budget + d.budget, actual: a.actual + d.actual, committed: a.committed + d.committed }),
    { budget: 0, actual: 0, committed: 0 }
  );

  return (
    <CfoSortableTable
      rows={rows}
      rowKey={(r) => r.name}
      getRowClass={(d) => (cfoRag((d.actual / d.budget) * 100) === "r" ? "alert" : undefined)}
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
        { key: "utilised", header: "Utilised", align: "right", sortValue: (d) => (d.actual / d.budget) * 100, render: (d) => cfoPct((d.actual / d.budget) * 100) },
        { key: "rag", header: "RAG", sortValue: (d) => cfoRagLabel((d.actual / d.budget) * 100), render: (d) => <RagBadge utilisedPct={(d.actual / d.budget) * 100} /> },
        { key: "owner", header: "Owner", sortValue: (d) => d.owner, render: (d) => d.owner },
      ]}
      foot={
        <>
          <td className="py-2 px-3 font-semibold">Total</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.budget)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.actual)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.committed)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoN0(totals.budget - totals.actual - totals.committed)}</td>
          <td className="py-2 px-3 text-right tnum">{cfoPct((totals.actual / totals.budget) * 100)}</td>
          <td colSpan={2} />
        </>
      }
    />
  );
}

function VendorTable() {
  const riskTone = (risk: string) =>
    risk === "High" ? pillTones.bad : risk === "Medium" ? pillTones.amber : pillTones.ok;

  return (
    <CfoSortableTable
      rows={CFO_DEMO.vendors}
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
        { key: "cycle", header: "Cycle (d)", align: "right", sortValue: (v) => v.cycle, render: (v) => cfoN1(v.cycle) },
        { key: "po", header: "PO-backed", align: "right", sortValue: (v) => v.po, render: (v) => `${v.po}%` },
        { key: "risk", header: "Risk", sortValue: (v) => v.risk, render: (v) => <StatusPill className={riskTone(v.risk)}>{v.risk}</StatusPill> },
      ]}
    />
  );
}

function AgeingStats() {
  const total = CFO_DEMO.ageing.reduce((a, x) => a + x.value, 0);
  const rows: { label: string; value: string; strong?: boolean }[] = [
    ...CFO_DEMO.ageing.map((a) => ({
      label: a.bucket,
      value: `${cfoN0(a.value)} (${cfoPct((a.value / total) * 100)})`,
    })),
    { label: "Total outstanding", value: cfoN0(total), strong: true },
    { label: "Disputed / on hold", value: "184,600" },
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

export function CfoCommandCentre({ tenantName }: { tenantName?: string }) {
  const cs = CFO_DEMO.cashSummary;
  const vc = CFO_DEMO.vendorConcentration;

  return (
    <div data-testid="cfo-command-centre">
      <SectionHead
        title="Position & liquidity"
        hint={`All figures AUD, consolidated, FY26 YTD to 31 Aug 2026${tenantName ? ` · ${tenantName}` : ""}`}
      />
      <PrimaryKpis />

      <SectionHead title="Efficiency & automation value" />
      <SecondaryKpis />

      <SectionHead title="Cash & liability outlook" />
      <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PanelCard
          title="13-week rolling cash outflow forecast"
          meta="Confirmed, probable, recurring, reimbursements, advances, tax · cumulative line"
          flushBody
          foot={
            <>
              <span>Next week <strong className="tnum text-foreground">{cfoN0(cs.nextWeek)}</strong></span>
              <span>13-week total <strong className="tnum text-foreground">{cfoN0(cs.total13Week)}</strong></span>
              <span>Peak week {cs.peakLabel} <strong className="tnum text-foreground">{cfoN0(cs.peakWeek)}</strong></span>
              <span>Coverage ratio <strong className="text-foreground">{cs.coverageRatio}×</strong></span>
            </>
          }
        >
          <CashForecastChart />
        </PanelCard>

        <PanelCard title="AP ageing" meta={`Total ${cfoN0(CFO_DEMO.apAgeingTotal)}`} flushBody aside={<AgeingStats />}>
          <AgeingChart />
        </PanelCard>
      </div>

      <SectionHead title="Budget, concentration & risk" />
      <div className="grid gap-4 items-start lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <PanelCard title="Budget vs actual vs committed — by department" meta="FY26 YTD · AUD" flushBody>
          <BudgetChart />
        </PanelCard>
        <PanelCard
          title="Vendor concentration"
          meta={`Top 10 = ${vc.top10Pct}% of spend`}
          flushBody
          foot={
            <>
              <span>Non-PO spend <strong className="tnum text-foreground">{vc.nonPoSpend}%</strong></span>
              <span>Contracted <strong className="text-foreground">{vc.contractedOf10} of 10</strong></span>
              <span>{vc.highRiskCount} high-risk vendor</span>
            </>
          }
        >
          <ParetoChart />
        </PanelCard>
      </div>

      <div className="grid gap-4 mt-4">
        <PanelCard title="Budget vs actual vs committed (encumbrance)" meta="RAG on actual vs budget" flushBody>
          <DeptTable />
        </PanelCard>
        <PanelCard title="Top vendors" meta="Spend YTD · cycle time · PO coverage" flushBody>
          <VendorTable />
        </PanelCard>
      </div>

      <div className="grid gap-4 items-start mt-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
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
