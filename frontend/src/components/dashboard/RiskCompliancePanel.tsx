import { useMemo, useState } from "react";
import { ChartDonut, ListBullets } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Cell, Pie, PieChart, ResponsiveContainer, Sector, Tooltip } from "recharts";
import { ChartTooltip } from "@/components/ChartTooltip";
import { Card } from "@/components/ui/card";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import {
  kpiModuleSolidFill,
  kpiStatusChipClass,
  type KpiModuleColor,
} from "@/lib/kpiModuleColors";

export type RiskComplianceRow = {
  id: string;
  label: string;
  count: number;
  href: string;
  tone: KpiModuleColor;
  badge: string;
};

export type RiskView = "list" | "donut";

/** Empty risk rows when overview has no risk_compliance payload. */
export const PLACEHOLDER_RISK_ROWS: RiskComplianceRow[] = [
  {
    id: "duplicates",
    label: "Duplicate documents",
    count: 0,
    href: "/approvals",
    tone: "rust",
    badge: "Review",
  },
  {
    id: "fraud",
    label: "Fraud invoices",
    count: 0,
    href: "/upload?view=detailed&q=DT-21",
    tone: "rose",
    badge: "Urgent",
  },
  {
    id: "bank",
    label: "Bank changes",
    count: 0,
    href: "/upload?view=detailed&q=DT-23",
    tone: "violet",
    badge: "Monitor",
  },
  {
    id: "counterparties",
    label: "New counterparties",
    count: 0,
    href: "/creations?tab=vendors",
    tone: "green",
    badge: "New",
  },
];

const PIE_HOVER_OFFSET = 3;
/** Visible but not oversized — fixed box so Recharts always has dimensions. */
const DONUT_PX = 156;

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
  const {
    cx = 0,
    cy = 0,
    innerRadius = 0,
    outerRadius = 0,
    startAngle,
    endAngle,
    fill,
  } = props;
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

export function RiskCompliancePanel({
  rows = PLACEHOLDER_RISK_ROWS,
  className,
  view: viewProp,
  onViewChange,
}: {
  rows?: RiskComplianceRow[];
  className?: string;
  view?: RiskView;
  onViewChange?: (view: RiskView) => void;
}) {
  const { theme } = useTheme();
  const [internalView, setInternalView] = useState<RiskView>("list");
  const view = viewProp ?? internalView;
  const setView = (next: RiskView) => {
    onViewChange?.(next);
    if (viewProp === undefined) setInternalView(next);
  };
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const chartData = useMemo(
    () =>
      rows.map((row) => ({
        id: row.id,
        name: row.label,
        value: row.count,
        tone: row.tone,
        href: row.href,
        // Light: soft pastels. Dark: deep accents.
        fill: kpiModuleSolidFill(row.tone, theme),
      })),
    [rows, theme]
  );

  const total = useMemo(
    () => chartData.reduce((sum, row) => sum + row.value, 0),
    [chartData]
  );

  return (
    <Card
      className={cn(
        "dash-card--elevated p-5 h-full flex flex-col",
        view === "donut" && "min-h-[17rem]",
        className
      )}
      data-testid="dashboard-risk-compliance"
      data-view={view}
    >
      <div className="flex items-start justify-between gap-2 mb-5 shrink-0">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">Attention needed</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">Exceptions requiring review</p>
        </div>
        <div
          className="inline-flex items-center rounded-full border border-border/70 bg-muted/40 p-0.5 shrink-0"
          role="group"
          aria-label="Risk view"
        >
          <button
            type="button"
            data-testid="risk-view-list"
            aria-pressed={view === "list"}
            title="List view"
            onClick={() => setView("list")}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors",
              view === "list"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <ListBullets size={14} weight="bold" aria-hidden />
            <span className="sr-only">List</span>
          </button>
          <button
            type="button"
            data-testid="risk-view-donut"
            aria-pressed={view === "donut"}
            title="Donut view"
            onClick={() => setView("donut")}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors",
              view === "donut"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <ChartDonut size={14} weight="bold" aria-hidden />
            <span className="sr-only">Donut</span>
          </button>
        </div>
      </div>

      {view === "donut" ? (
        <div
          className="flex flex-1 items-center gap-4 py-2 min-w-0"
          style={{ minHeight: DONUT_PX + 16 }}
          data-testid="risk-compliance-donut"
        >
          {total <= 0 ? (
            <p className="text-sm text-muted-foreground">No risk items for this period.</p>
          ) : (
            <>
              <div
                className="relative shrink-0"
                style={{ width: DONUT_PX, height: DONUT_PX }}
              >
                <ResponsiveContainer width="100%" height="100%" minWidth={DONUT_PX} minHeight={DONUT_PX}>
                  <PieChart>
                    <Pie
                      data={chartData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={46}
                      outerRadius={66}
                      stroke="none"
                      paddingAngle={2}
                      isAnimationActive
                      animationDuration={500}
                      animationEasing="ease-out"
                      activeIndex={activeIndex ?? undefined}
                      activeShape={renderActivePieSector}
                      onMouseEnter={(_, index) => setActiveIndex(index)}
                      onMouseLeave={() => setActiveIndex(null)}
                    >
                      {chartData.map((row, index) => (
                        <Cell
                          key={row.id}
                          fill={row.fill}
                          opacity={activeIndex === null || activeIndex === index ? 1 : 0.45}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      content={({ active, payload }) => (
                        <ChartTooltip
                          active={active}
                          payload={payload}
                          label={payload?.[0]?.name}
                          valueFormatter={(v) => `${Number(v).toLocaleString()}`}
                        />
                      )}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-lg font-semibold tnum tabular-nums leading-none text-foreground">
                    {total.toLocaleString()}
                  </span>
                  <span className="mt-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    flags
                  </span>
                </div>
              </div>
              <ul
                className="flex flex-col justify-center gap-1.5 min-w-0 flex-1"
                data-testid="risk-compliance-donut-legend"
              >
                {chartData.map((row, index) => (
                  <li key={row.id}>
                    <Link
                      to={row.href}
                      data-testid={`risk-donut-legend-${row.id}`}
                      className={cn(
                        "flex items-center gap-2 rounded-md px-1.5 py-1 text-sm",
                        "hover-elevate transition-colors",
                        activeIndex !== null && activeIndex !== index && "opacity-45"
                      )}
                      onMouseEnter={() => setActiveIndex(index)}
                      onMouseLeave={() => setActiveIndex(null)}
                    >
                      <span
                        className="h-2 w-2 rounded-full shrink-0"
                        style={{ backgroundColor: row.fill }}
                        aria-hidden
                      />
                      <span className="flex-1 min-w-0 truncate font-medium">{row.name}</span>
                      <span className="tnum font-semibold tabular-nums shrink-0">
                        {row.value.toLocaleString()}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : (
        <ul className="flex flex-col justify-between flex-1 gap-1" data-testid="risk-compliance-list">
          {rows.map((row) => (
            <li key={row.id}>
              <Link
                to={row.href}
                data-testid={`risk-row-${row.id}`}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-1.5 py-2 text-sm",
                  "hover-elevate transition-colors"
                )}
              >
                <span
                  className="h-2.5 w-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: kpiModuleSolidFill(row.tone, theme) }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                  {row.label}
                </span>
                <span className={cn(kpiStatusChipClass(row.tone), "shrink-0")}>{row.badge}</span>
                <span className="w-7 shrink-0 text-right tnum font-semibold tabular-nums text-foreground">
                  {row.count}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
