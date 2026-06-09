import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

function Sparkline({ data, color = "hsl(var(--chart-1))" }: { data: number[]; color?: string }) {
  const chartData = data.map((v, i) => ({ i, v }));
  const gradId = `spark-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <ResponsiveContainer width="100%" height={36}>
      <AreaChart data={chartData} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.6}
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
  testid,
}: {
  label: string;
  value: string | number;
  delta?: { dir: "up" | "down" | "flat"; text: string; good?: boolean };
  spark?: number[];
  testid?: string;
}) {
  const Icon = delta?.dir === "up" ? TrendingUp : delta?.dir === "down" ? TrendingDown : Minus;
  const positive = delta?.good ?? delta?.dir === "up";

  return (
    <Card className="p-4 flex flex-col gap-2 min-w-0" data-testid={testid}>
      <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide truncate">
        {label}
      </span>
      <div className="flex items-end justify-between gap-2">
        <span className="text-lg font-semibold tnum tracking-tight truncate">{value}</span>
      </div>
      <div className="flex items-center justify-between gap-2">
        {delta ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 text-xs font-medium tnum",
              delta.dir === "flat"
                ? "text-muted-foreground"
                : positive
                  ? "text-[hsl(var(--chart-1))]"
                  : "text-destructive"
            )}
          >
            <Icon className="h-3 w-3" />
            {delta.text}
          </span>
        ) : (
          <span />
        )}
        {spark && (
          <div className="w-20 h-9 shrink-0">
            <Sparkline data={spark} />
          </div>
        )}
      </div>
    </Card>
  );
}
