import { cn } from "@/lib/cn";

export function ConfidenceBar({ value }: { value: number }) {
  const tone =
    value >= 90
      ? "bg-[hsl(var(--chart-1))]"
      : value >= 70
        ? "bg-primary"
        : value >= 40
          ? "bg-[#9c4e2a] dark:bg-[#edc0a6]"
          : "bg-destructive";
  return (
    <div className="inline-flex items-center gap-2">
      <div className="h-1.5 w-16 shrink-0 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span className="tnum text-[10px] text-muted-foreground w-7 text-left">{value}%</span>
    </div>
  );
}
