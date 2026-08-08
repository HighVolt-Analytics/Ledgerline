import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import { kpiModuleFill, type KpiModuleColor } from "@/lib/kpiModuleColors";

export type CaptureSourceId = "email" | "whatsapp" | "viber" | "upload";

export type CaptureSourceMetric = "documents" | "time_saved" | "manual_time" | "cost_saved";

export type CaptureSourceRow = {
  id: CaptureSourceId;
  label: string;
  documentCount: number;
  avgTimeSavedMinutes: number;
  timeSavedMinutes: number;
  manualMinutes: number;
  costSaved: number;
  moduleColor: KpiModuleColor;
  href: string;
};

/** Empty capture-source rows when overview has no channel data yet. */
export const PLACEHOLDER_CAPTURE_SOURCES: CaptureSourceRow[] = [
  {
    id: "email",
    label: "Email",
    documentCount: 0,
    avgTimeSavedMinutes: 12,
    timeSavedMinutes: 0,
    manualMinutes: 0,
    costSaved: 0,
    moduleColor: "blue",
    href: "/upload?channel=email",
  },
  {
    id: "whatsapp",
    label: "WhatsApp",
    documentCount: 0,
    avgTimeSavedMinutes: 15,
    timeSavedMinutes: 0,
    manualMinutes: 0,
    costSaved: 0,
    moduleColor: "violet",
    href: "/upload?channel=whatsapp",
  },
  {
    id: "viber",
    label: "Viber",
    documentCount: 0,
    avgTimeSavedMinutes: 12,
    timeSavedMinutes: 0,
    manualMinutes: 0,
    costSaved: 0,
    moduleColor: "rose",
    href: "/upload?channel=viber",
  },
  {
    id: "upload",
    label: "Uploads",
    documentCount: 0,
    avgTimeSavedMinutes: 11,
    timeSavedMinutes: 0,
    manualMinutes: 0,
    costSaved: 0,
    moduleColor: "rust",
    href: "/upload?channel=upload",
  },
];

const METRIC_OPTIONS: { value: CaptureSourceMetric; label: string }[] = [
  { value: "documents", label: "Documents" },
  { value: "time_saved", label: "Time Saved" },
  { value: "manual_time", label: "Manual Time" },
  { value: "cost_saved", label: "Cost Saved" },
];

const METRIC_SUBTITLE: Record<CaptureSourceMetric, string> = {
  documents: "Document volume by inbound channel",
  time_saved: "Estimated time saved by inbound channel",
  manual_time: "Manual processing time by inbound channel",
  cost_saved: "Estimated cost saved by inbound channel",
};

const METRIC_FOOTER: Record<CaptureSourceMetric, string> = {
  documents: "Tracked source volume",
  time_saved: "Tracked time saved",
  manual_time: "Tracked manual time",
  cost_saved: "Tracked source value",
};

function metricValue(row: CaptureSourceRow, metric: CaptureSourceMetric): number {
  switch (metric) {
    case "documents":
      return row.documentCount;
    case "time_saved":
      return row.timeSavedMinutes;
    case "manual_time":
      return row.manualMinutes;
    case "cost_saved":
      return row.costSaved;
  }
}

function formatMetric(value: number, metric: CaptureSourceMetric): string {
  if (metric === "documents") return value.toLocaleString();
  if (metric === "cost_saved") return `$${value.toLocaleString()}`;
  return `${value.toLocaleString()} min`;
}

export function CaptureSourceBars({
  rows = PLACEHOLDER_CAPTURE_SOURCES,
  className,
  expand = false,
}: {
  rows?: CaptureSourceRow[];
  className?: string;
  /** Stretch with Risk & Compliance when that card grows (e.g. donut view). */
  expand?: boolean;
}) {
  const { theme } = useTheme();
  const [metric, setMetric] = useState<CaptureSourceMetric>("cost_saved");

  const max = useMemo(
    () => Math.max(1, ...rows.map((r) => metricValue(r, metric))),
    [rows, metric]
  );

  const total = useMemo(
    () => rows.reduce((sum, r) => sum + metricValue(r, metric), 0),
    [rows, metric]
  );

  return (
    <Card
      className={cn(
        "dash-card--elevated p-5 flex flex-col h-full transition-[min-height] duration-300",
        expand && "min-h-[17rem]",
        className
      )}
      data-testid="dashboard-capture-sources"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5 shrink-0">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">Value by source</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{METRIC_SUBTITLE[metric]}</p>
        </div>
        <Select
          value={metric}
          onValueChange={(v) => setMetric(v as CaptureSourceMetric)}
          options={METRIC_OPTIONS}
          className="w-[160px] h-8 text-xs"
          size="sm"
          data-testid="select-capture-source-metric"
        />
      </div>

      <div
        className={cn(
          "flex flex-col w-full flex-1 transition-[gap] duration-300",
          expand ? "justify-between gap-5" : "justify-start gap-4"
        )}
        data-testid="capture-source-bars"
      >
        {rows.map((row) => {
          const value = metricValue(row, metric);
          const pct = Math.max(0, Math.min(100, Math.round((value / max) * 100)));
          const fill = kpiModuleFill(row.moduleColor, theme);

          return (
            <div
              key={row.id}
              className="group relative w-full"
              data-testid={`capture-source-${row.id}`}
            >
              <Link
                to={row.href}
                className="grid w-full items-center"
                style={{
                  gridTemplateColumns: "108px minmax(0, 1fr) 80px",
                  columnGap: 12,
                }}
                title={[
                  row.label,
                  `${row.documentCount.toLocaleString()} documents`,
                  `${row.avgTimeSavedMinutes} min avg saved`,
                  `${row.timeSavedMinutes.toLocaleString()} min total saved`,
                  `${row.manualMinutes.toLocaleString()} min manual time`,
                ].join("\n")}
              >
                <span className="flex min-w-0 items-center gap-2.5 overflow-hidden text-sm font-medium text-foreground">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: fill }}
                    aria-hidden
                  />
                  <span className="truncate">{row.label}</span>
                </span>

                <div className="h-2.5 w-full min-w-0 overflow-hidden rounded-full bg-muted/50">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${pct}%`,
                      maxWidth: "100%",
                      backgroundColor: fill,
                      marginInlineStart: 0,
                    }}
                  />
                </div>

                <span className="overflow-hidden text-ellipsis whitespace-nowrap text-right text-sm font-medium tnum tabular-nums text-foreground">
                  {formatMetric(value, metric)}
                </span>
              </Link>

              <div
                className={cn(
                  "pointer-events-none absolute left-0 top-full z-10 mt-1 hidden w-56 rounded-md border border-border bg-popover p-2.5 text-xs shadow-md",
                  "group-hover:block group-focus-within:block"
                )}
                role="tooltip"
              >
                <p className="font-semibold text-foreground mb-1.5">{row.label}</p>
                <ul className="space-y-0.5 text-muted-foreground tnum">
                  <li>{row.documentCount.toLocaleString()} documents</li>
                  <li>{row.avgTimeSavedMinutes} min avg saved</li>
                  <li>{row.timeSavedMinutes.toLocaleString()} min total saved</li>
                  <li>{row.manualMinutes.toLocaleString()} min manual time</li>
                </ul>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-5 pt-4 border-t border-border/60 flex items-center justify-between gap-3 shrink-0">
        <span className="text-sm font-semibold text-foreground">{METRIC_FOOTER[metric]}</span>
        <span className="text-base font-semibold tnum tabular-nums text-foreground">
          {formatMetric(total, metric)}
        </span>
      </div>
    </Card>
  );
}
