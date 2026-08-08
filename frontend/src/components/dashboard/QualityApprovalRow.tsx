import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CheckCircle, Pulse, Queue } from "@phosphor-icons/react";
import { ChartTooltip } from "@/components/ChartTooltip";
import { Card } from "@/components/ui/card";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";

export type ExtractionQualityPoint = {
  metric: string;
  accuracy: number;
};

export type ApprovalQueueStats = {
  pending: number;
  valueLabel: string;
  medianTimeLabel: string;
};

/** Empty quality / queue stats when overview has no payload yet. */
export const PLACEHOLDER_EXTRACTION_QUALITY: ExtractionQualityPoint[] = [
  { metric: "Header", accuracy: 0 },
  { metric: "Line items", accuracy: 0 },
  { metric: "Tax/GST", accuracy: 0 },
  { metric: "GL coding", accuracy: 0 },
];

export const PLACEHOLDER_APPROVAL_QUEUE: ApprovalQueueStats = {
  pending: 0,
  valueLabel: "—",
  medianTimeLabel: "—",
};

const CHART_HEIGHT = 200;
const CHART_MARGIN = { top: 12, right: 16, left: 0, bottom: 4 };

const FILL_LIGHT = "#245e8d";
const FILL_DARK = "#245e8d";

export function ExtractionQualityCard({
  points = PLACEHOLDER_EXTRACTION_QUALITY,
  className,
}: {
  points?: ExtractionQualityPoint[];
  className?: string;
}) {
  const { theme } = useTheme();
  const lineColor = theme === "dark" ? FILL_DARK : FILL_LIGHT;
  const avg =
    points.length > 0
      ? points.reduce((sum, p) => sum + p.accuracy, 0) / points.length
      : 0;

  return (
    <Card
      className={cn("dash-card--elevated p-4 h-full flex flex-col", className)}
      data-testid="dashboard-extraction-quality"
    >
      <div className="flex items-baseline justify-between gap-3 mb-3 shrink-0">
        <h3 className="text-sm font-semibold inline-flex items-center gap-2">
          <Pulse size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
          Extraction Quality
        </h3>
        <p className="text-xs text-muted-foreground tnum tabular-nums">
          Avg{" "}
          <span className="font-semibold text-foreground">{avg.toFixed(1)}%</span>
        </p>
      </div>

      <div
        className="w-full"
        style={{ width: "100%", height: CHART_HEIGHT, minHeight: CHART_HEIGHT }}
        data-testid="extraction-quality-chart"
      >
        <ResponsiveContainer
          width="100%"
          height={CHART_HEIGHT}
          minWidth={180}
          minHeight={CHART_HEIGHT}
        >
          <LineChart data={points} margin={CHART_MARGIN}>
            <CartesianGrid
              stroke="hsl(var(--border))"
              strokeDasharray="3 3"
              vertical={false}
            />
            <XAxis
              dataKey="metric"
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--muted-foreground))"
              tickLine={false}
              axisLine={false}
              interval={0}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              stroke="hsl(var(--muted-foreground))"
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}%`}
              width={42}
            />
            <Tooltip
              content={({ active, payload, label }) => (
                <ChartTooltip
                  active={active}
                  payload={payload}
                  label={label}
                  valueFormatter={(v) => `${Number(v).toFixed(1)}%`}
                />
              )}
            />
            <Line
              type="monotone"
              dataKey="accuracy"
              name="Accuracy"
              stroke={lineColor}
              strokeWidth={2.5}
              dot={{ r: 4, fill: lineColor, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              isAnimationActive
              animationDuration={500}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export function ApprovalQueueCard({
  stats = PLACEHOLDER_APPROVAL_QUEUE,
  className,
}: {
  stats?: ApprovalQueueStats;
  className?: string;
}) {
  return (
    <Card
      className={cn("dash-card--elevated p-4 h-full flex flex-col", className)}
      data-testid="dashboard-approval-queue"
    >
      <h3 className="text-sm font-semibold mb-3 shrink-0 inline-flex items-center gap-2">
        <Queue size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
        Approval Queue
      </h3>
      <dl className="flex flex-col flex-1 justify-center">
        <div className="flex items-baseline justify-between gap-3 py-2.5">
          <dt className="text-sm text-muted-foreground inline-flex items-center gap-1.5">
            <CheckCircle size={14} weight="duotone" className="text-muted-foreground" aria-hidden />
            Pending
          </dt>
          <dd className="text-sm font-semibold tnum tabular-nums ds-warning-text">
            {stats.pending.toLocaleString()}
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-3 py-2.5 border-t border-border/40">
          <dt className="text-sm text-muted-foreground">Value</dt>
          <dd className="text-sm font-semibold tnum tabular-nums">{stats.valueLabel}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-3 py-2.5 border-t border-border/40">
          <dt className="text-sm text-muted-foreground">Median time</dt>
          <dd className="text-sm font-semibold tnum tabular-nums">
            {stats.medianTimeLabel}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

export function QualityApprovalRow({
  extraction = PLACEHOLDER_EXTRACTION_QUALITY,
  approval = PLACEHOLDER_APPROVAL_QUEUE,
  className,
}: {
  extraction?: ExtractionQualityPoint[];
  approval?: ApprovalQueueStats;
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-4 lg:grid-cols-2 lg:items-stretch mb-6", className)}
      data-testid="dashboard-quality-approval-row"
    >
      <ExtractionQualityCard points={extraction} />
      <ApprovalQueueCard stats={approval} />
    </div>
  );
}
