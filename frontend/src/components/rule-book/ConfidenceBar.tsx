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
    <div className="flex items-center gap-2 min-w-[100px]">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span className="tnum text-[10px] text-muted-foreground w-7 text-right">{value}%</span>
    </div>
  );
}
