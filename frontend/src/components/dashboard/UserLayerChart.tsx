import { useMemo, useState } from "react";
import { UsersThree } from "@phosphor-icons/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import { kpiModuleFill, type KpiModuleColor } from "@/lib/kpiModuleColors";

export type UserLayerMetricId =
  | "email_mapped"
  | "phone_synced"
  | "doc_types"
  | "manual_handoff"
  | "vendors";

export type PipelineStageId =
  | "document_fetched"
  | "pending_confirmation"
  | "pending_approval"
  | "pending_posting"
  | "pending_payment";

export type UserLayerMetric = {
  id: UserLayerMetricId;
  label: string;
  tone: KpiModuleColor;
  /** Counts keyed by pipeline stage id. */
  stages: Record<PipelineStageId, number>;
};

const PIPELINE_STAGES: { id: PipelineStageId; label: string; shortLabel: string }[] = [
  { id: "document_fetched", label: "Document Fetched", shortLabel: "Fetched" },
  { id: "pending_confirmation", label: "Pending For Confirmation", shortLabel: "Confirm" },
  { id: "pending_approval", label: "Pending For Approval", shortLabel: "Approval" },
  { id: "pending_posting", label: "Pending For Posting", shortLabel: "Posting" },
  { id: "pending_payment", label: "Pending For Payment", shortLabel: "Payment" },
];

/** Placeholder user-layer coverage until overview API exposes these metrics. */
export const PLACEHOLDER_USER_LAYER: UserLayerMetric[] = [
  {
    id: "email_mapped",
    label: "No. of E-mail ID Mapped",
    tone: "blue",
    stages: {
      document_fetched: 42,
      pending_confirmation: 8,
      pending_approval: 5,
      pending_posting: 3,
      pending_payment: 1,
    },
  },
  {
    id: "phone_synced",
    label: "Phone no. synched",
    tone: "violet",
    stages: {
      document_fetched: 28,
      pending_confirmation: 4,
      pending_approval: 2,
      pending_posting: 1,
      pending_payment: 0,
    },
  },
  {
    id: "doc_types",
    label: "No. of Doc Types",
    tone: "green",
    stages: {
      document_fetched: 50,
      pending_confirmation: 12,
      pending_approval: 8,
      pending_posting: 6,
      pending_payment: 4,
    },
  },
  {
    id: "manual_handoff",
    label: "Manual Handoff",
    tone: "rust",
    stages: {
      document_fetched: 20,
      pending_confirmation: 9,
      pending_approval: 7,
      pending_posting: 5,
      pending_payment: 3,
    },
  },
  {
    id: "vendors",
    label: "No of Vendors",
    tone: "rose",
    stages: {
      document_fetched: 50,
      pending_confirmation: 2,
      pending_approval: 0,
      pending_posting: 2,
      pending_payment: 2,
    },
  },
];

const CHART_HEIGHT = 220;
const CHART_MARGIN = { top: 12, right: 8, left: 0, bottom: 4 };

export function UserLayerChart({
  metrics = PLACEHOLDER_USER_LAYER,
  className,
}: {
  metrics?: UserLayerMetric[];
  className?: string;
}) {
  const { theme } = useTheme();
  const [metricId, setMetricId] = useState<UserLayerMetricId>(
    metrics[0]?.id ?? "vendors"
  );

  const selected = useMemo(
    () => metrics.find((m) => m.id === metricId) ?? metrics[0] ?? null,
    [metrics, metricId]
  );

  const chartData = useMemo(() => {
    if (!selected) return [];
    const fill = kpiModuleFill(selected.tone, theme);
    return PIPELINE_STAGES.map((stage) => ({
      stageId: stage.id,
      label: stage.shortLabel,
      fullLabel: stage.label,
      value: selected.stages[stage.id] ?? 0,
      metricLabel: selected.label,
      fill,
    }));
  }, [selected, theme]);

  const options = useMemo(
    () =>
      metrics.map((m) => ({
        value: m.id,
        label: m.label,
      })),
    [metrics]
  );

  return (
    <Card
      className={cn("dash-card--elevated p-4 mb-6", className)}
      data-testid="dashboard-user-layer"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold inline-flex items-center gap-2">
            <UsersThree size={16} weight="duotone" className="text-muted-foreground" aria-hidden />
            User Layer
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Coverage across the document pipeline
          </p>
        </div>
        <Select
          value={selected?.id ?? metricId}
          onValueChange={(v) => setMetricId(v as UserLayerMetricId)}
          options={options}
          className="w-[220px] h-8 text-xs"
          size="sm"
          data-testid="select-user-layer-metric"
        />
      </div>

      {chartData.length === 0 ? (
        <p className="text-sm text-muted-foreground flex items-center" style={{ height: CHART_HEIGHT }}>
          No user-layer metrics for this period.
        </p>
      ) : (
        <div
          className="w-full"
          style={{ width: "100%", height: CHART_HEIGHT, minHeight: CHART_HEIGHT }}
          data-testid="user-layer-chart"
        >
          <ResponsiveContainer width="100%" height={CHART_HEIGHT} minWidth={200} minHeight={CHART_HEIGHT}>
            <BarChart data={chartData} margin={CHART_MARGIN}>
              <CartesianGrid
                stroke="hsl(var(--border))"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--muted-foreground))"
                tickLine={false}
                axisLine={false}
                interval={0}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                stroke="hsl(var(--muted-foreground))"
                tickLine={false}
                axisLine={false}
                width={40}
              />
              <Tooltip
                cursor={{ fill: "hsl(var(--muted) / 0.45)" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const row = payload[0]?.payload as (typeof chartData)[number] | undefined;
                  if (!row) return null;
                  return (
                    <div className="chart-tooltip" data-testid="user-layer-tooltip">
                      <p className="chart-tooltip-label">{row.fullLabel}</p>
                      <p className="text-[11px] text-muted-foreground mb-1">
                        {row.metricLabel}
                      </p>
                      <p
                        className="chart-tooltip-value tnum"
                        style={{ color: row.fill }}
                      >
                        {row.value.toLocaleString()}
                      </p>
                    </div>
                  );
                }}
              />
              <Bar
                dataKey="value"
                name="Count"
                radius={[4, 4, 0, 0]}
                maxBarSize={56}
                isAnimationActive
                animationDuration={450}
              >
                {chartData.map((row) => (
                  <Cell key={row.stageId} fill={row.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
