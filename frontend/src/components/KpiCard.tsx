import type { Icon } from "@phosphor-icons/react";
import { Minus, TrendDown, TrendUp } from "@phosphor-icons/react";
import { lazy, Suspense } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { kpiModuleIconClass, type KpiModuleColor } from "@/lib/kpiModuleColors";

export type { KpiModuleColor };

const KpiSparkline = lazy(() =>
  import("@/components/KpiSparkline").then((m) => ({ default: m.KpiSparkline }))
);

export function KpiCard({
  label,
  value,
  delta,
  hint,
  spark,
  icon: Icon,
  moduleColor = "cyan",
  testid,
  onClick,
}: {
  label: string;
  value: string | number;
  delta?: { dir: "up" | "down" | "flat"; text: string; good?: boolean };
  /** Muted footnote when there is no delta (e.g. "per document"). */
  hint?: string;
  spark?: number[];
  icon?: Icon;
  moduleColor?: KpiModuleColor;
  testid?: string;
  onClick?: () => void;
}) {
  const DeltaIcon = delta?.dir === "up" ? TrendUp : delta?.dir === "down" ? TrendDown : Minus;
  const positive = delta?.good ?? delta?.dir === "up";
  const showSpark = Boolean(spark?.length) && !Icon;

  return (
    <Card
      className={cn(
        "kpi-card kpi-card--elevated p-4 min-w-0",
        onClick && "cursor-pointer hover-elevate transition-shadow"
      )}
      data-testid={testid}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="flex flex-col gap-3 min-w-0">
        {Icon && (
          <span className={kpiModuleIconClass(moduleColor)} aria-hidden>
            <Icon size={18} weight="duotone" />
          </span>
        )}

        <div className="min-w-0 space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground truncate leading-snug">
            {label}
          </p>
          <p className="text-[1.375rem] font-semibold tnum tracking-tight truncate leading-none text-foreground">
            {value}
          </p>

          {(delta || hint || showSpark) && (
            <div className="flex items-center justify-between gap-2 pt-0.5 min-h-[1.125rem]">
              {delta ? (
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5 text-xs font-medium tnum",
                    delta.dir === "flat"
                      ? "text-muted-foreground"
                      : positive
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-destructive"
                  )}
                >
                  <DeltaIcon size={12} weight="bold" />
                  {delta.text}
                </span>
              ) : hint ? (
                <span className="text-xs text-muted-foreground truncate">{hint}</span>
              ) : (
                <span />
              )}
              {showSpark && (
                <div className="h-9 w-20 shrink-0">
                  <Suspense fallback={null}>
                    <KpiSparkline data={spark!} />
                  </Suspense>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
