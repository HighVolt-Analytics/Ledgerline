import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function InboxConfidenceBadge({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground">—</span>;
  }
  const tone =
    value >= 95
      ? "border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]"
      : value >= 80
        ? "border-[hsl(43_74%_49%/0.5)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]"
        : "border-destructive/40 text-destructive";
  return (
    <Badge variant="outline" className={cn("tnum font-medium", tone)}>
      {value}%
    </Badge>
  );
}
