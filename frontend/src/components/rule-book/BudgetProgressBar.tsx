import { cn } from "@/lib/cn";

export function BudgetProgressBar({
  value,
  max,
  label,
}: {
  value: number;
  max: number;
  label?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const tone =
    pct >= 100
      ? "bg-destructive"
      : pct >= 80
        ? "bg-[rgb(var(--system-yellow-rgb)/1)]"
        : "bg-primary";

  return (
    <div className="min-w-0">
      {label && (
        <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
          <span>{label}</span>
          <span className="tnum">{pct}%</span>
        </div>
      )}
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
