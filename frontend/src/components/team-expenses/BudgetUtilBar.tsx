import { cn } from "@/lib/cn";

export function BudgetUtilBar({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const color =
    pct >= 90
      ? "bg-destructive"
      : pct >= 70
        ? "bg-[rgb(var(--system-yellow-rgb)/1)]"
        : "bg-primary";
  return (
    <div className="w-full h-2 rounded-full bg-muted overflow-hidden">
      <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}
