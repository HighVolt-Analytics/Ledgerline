import type { LucideIcon } from "lucide-react";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { kpiModuleIconClass, type KpiModuleColor } from "@/lib/kpiModuleColors";

export type { KpiModuleColor };

function Sparkline({ data, color = "hsl(var(--cyan-500))" }: { data: number[]; color?: string }) {
  const chartData = data.map((v, i) => ({ i, v }));
  const gradId = `spark-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <ResponsiveContainer width="100%" height={36}>
      <AreaChart data={chartData} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#${gradId})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function KpiCard({
  label,
  value,
  delta,
  spark,
  icon: Icon,
  moduleColor = "cyan",
  testid,
  onClick,
}: {
  label: string;
  value: string | number;
  delta?: { dir: "up" | "down" | "flat"; text: string; good?: boolean };
  spark?: number[];
  icon?: LucideIcon;
  moduleColor?: KpiModuleColor;
  testid?: string;
  onClick?: () => void;
}) {
  const DeltaIcon = delta?.dir === "up" ? TrendingUp : delta?.dir === "down" ? TrendingDown : Minus;
  const positive = delta?.good ?? delta?.dir === "up";
  const showSpark = Boolean(spark?.length) && !Icon;

  return (
    <Card
      className={cn(
        "kpi-card p-4 min-w-0 border-border/55 shadow-none",
        onClick && "cursor-pointer hover-elevate transition-colors"
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
      <div className="flex items-start gap-3">
        {Icon && (
          <span className={kpiModuleIconClass(moduleColor)} aria-hidden>
            <Icon strokeWidth={2} />
          </span>
        )}

        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-xs font-medium text-muted-foreground truncate">{label}</p>
          <p className="text-lg font-semibold tnum tracking-tight truncate leading-tight">{value}</p>

          {(delta || showSpark) && (
            <div className="flex items-center justify-between gap-2 pt-0.5">
              {delta ? (
                <span
                  className={cn(
                    "inline-flex items-center gap-0.5 text-xs font-medium tnum",
                    delta.dir === "flat"
                      ? "text-muted-foreground"
                      : positive
                        ? "text-[hsl(var(--cyan-600))] dark:text-[hsl(var(--cyan-400))]"
                        : "text-destructive"
                  )}
                >
                  <DeltaIcon className="h-3 w-3" />
                  {delta.text}
                </span>
              ) : (
                <span />
              )}
              {showSpark && (
                <div className="h-9 w-20 shrink-0">
                  <Sparkline data={spark!} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
