import type { Icon } from "@phosphor-icons/react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Gauge,
  SealCheck,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import {
  kpiModuleFill,
  kpiModuleIconClass,
  type KpiModuleColor,
} from "@/lib/kpiModuleColors";

export type AttentionPriority = {
  title: string;
  body: string;
  ctaLabel: string;
  ctaHref: string;
};

export type AttentionMetric = {
  label: string;
  value: string;
  deltaText: string;
  /** When true, use down-arrow (e.g. faster turnaround). */
  deltaDown?: boolean;
  deltaGood: boolean;
  /** 7 spark bars; last bar is emphasized. */
  bars: number[];
  icon: Icon;
  moduleColor: KpiModuleColor;
};

/** Placeholder attention strip until overview API exposes priority + throughput. */
export const PLACEHOLDER_PRIORITY: AttentionPriority = {
  title: "Three invoices need your approval.",
  body: "Two have a bank-account change and one has a duplicate-risk signal. Review them before the next payment run.",
  ctaLabel: "Review exceptions",
  ctaHref: "/approvals",
};

export const PLACEHOLDER_PROCESSED_TODAY: AttentionMetric = {
  label: "Processed today",
  value: "38",
  deltaText: "12% vs. yesterday",
  deltaGood: true,
  bars: [14, 18, 16, 22, 20, 28, 38],
  icon: SealCheck,
  moduleColor: "cyan",
};

export const PLACEHOLDER_TURNAROUND: AttentionMetric = {
  label: "Average turnaround",
  value: "4m 18s",
  deltaText: "46s faster this week",
  deltaDown: true,
  deltaGood: true,
  bars: [40, 36, 34, 30, 28, 26, 20],
  icon: Gauge,
  moduleColor: "rose",
};

const BAR_AREA_H = 56;

function MiniBars({
  values,
  moduleColor,
}: {
  values: number[];
  moduleColor: KpiModuleColor;
}) {
  const { theme } = useTheme();
  const fill = kpiModuleFill(moduleColor, theme);
  const max = Math.max(1, ...values);

  return (
    <div
      className="flex w-full items-end gap-1.5"
      style={{ height: BAR_AREA_H }}
      aria-hidden
    >
      {values.map((v, i) => {
        const heightPx = Math.max(12, Math.round((v / max) * BAR_AREA_H));
        const isLast = i === values.length - 1;
        return (
          <span
            key={i}
            className="block flex-1 rounded-md"
            style={{
              height: heightPx,
              minHeight: heightPx,
              backgroundColor: fill,
              opacity: isLast ? 1 : theme === "dark" ? 0.42 : 0.4,
            }}
          />
        );
      })}
    </div>
  );
}

function MetricCard({ metric }: { metric: AttentionMetric }) {
  const MetricIcon = metric.icon;
  const DeltaIcon = metric.deltaDown ? ArrowDownRight : ArrowUpRight;

  return (
    <Card
      className={cn(
        "dash-card--elevated attention-metric-card p-5 h-full flex flex-col min-w-0",
        "rounded-3xl bg-card"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] text-muted-foreground leading-none pt-1">{metric.label}</p>
        <span className={kpiModuleIconClass(metric.moduleColor)} aria-hidden>
          <MetricIcon size={18} weight="duotone" />
        </span>
      </div>
      <p className="mt-3 text-[2.25rem] font-semibold tracking-tight tnum tabular-nums leading-none text-foreground">
        {metric.value}
      </p>
      <p
        className={cn(
          "mt-2.5 inline-flex items-center gap-1 text-[12px] font-medium tnum",
          metric.deltaGood
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-destructive"
        )}
      >
        <DeltaIcon size={14} weight="bold" aria-hidden />
        {metric.deltaText}
      </p>
      <div className="mt-auto pt-5">
        <MiniBars values={metric.bars} moduleColor={metric.moduleColor} />
      </div>
    </Card>
  );
}

export function AttentionStrip({
  priority = PLACEHOLDER_PRIORITY,
  processed = PLACEHOLDER_PROCESSED_TODAY,
  turnaround = PLACEHOLDER_TURNAROUND,
  className,
}: {
  priority?: AttentionPriority;
  processed?: AttentionMetric;
  turnaround?: AttentionMetric;
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-4 lg:grid-cols-3 lg:items-stretch mb-6", className)}
      data-testid="dashboard-attention-strip"
    >
      <Card
        className={cn(
          "attention-priority-card p-5 h-full flex flex-col min-w-0 rounded-3xl",
          "bg-[#1c1c1e] border-transparent text-white shadow-none"
        )}
        data-testid="attention-priority"
      >
        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-white/55">
          Today&apos;s priority
        </p>
        <h3 className="mt-4 text-[1.35rem] font-semibold tracking-tight leading-[1.25] text-white">
          {priority.title}
        </h3>
        <p className="mt-3 text-[13px] text-white/60 leading-relaxed flex-1">
          {priority.body}
        </p>
        <Link
          to={priority.ctaHref}
          className="attention-priority-cta mt-6 inline-flex w-fit items-center gap-1.5 rounded-full px-4 py-2.5 text-[13px] font-medium transition-colors"
          data-testid="attention-priority-cta"
        >
          <span>{priority.ctaLabel}</span>
          <ArrowRight size={14} weight="bold" aria-hidden />
        </Link>
      </Card>

      <div className="h-full min-h-0" data-testid="attention-processed">
        <MetricCard metric={processed} />
      </div>
      <div className="h-full min-h-0" data-testid="attention-turnaround">
        <MetricCard metric={turnaround} />
      </div>
    </div>
  );
}
