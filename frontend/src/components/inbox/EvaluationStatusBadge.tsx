import type { Invoice } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { evaluationStatusDescription, evaluationStatusLabel } from "@/lib/invoice";

export function EvaluationStatusBadge({
  status,
}: {
  status: Invoice["evaluation_status"];
}) {
  const label = status ? evaluationStatusLabel(status) : "—";
  const title = evaluationStatusDescription(status);

  if (!status) {
    return (
      <span className="text-muted-foreground text-xs" title={title}>
        —
      </span>
    );
  }
  const tone =
    status === "auto_coded"
      ? "border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]"
      : status === "pending_vendor" || status === "awaiting_po"
        ? "border-destructive/40 text-destructive"
        : status === "unmatched_expense_vendor"
          ? "border-[hsl(43_74%_49%/0.5)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]"
          : "border-[hsl(43_74%_49%/0.5)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]";
  return (
    <Badge
      variant="outline"
      className={cn("text-xs font-medium", tone)}
      title={title}
    >
      {label}
    </Badge>
  );
}

export function RouteTargetBadge({ route }: { route: string | null | undefined }) {
  if (!route) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  return (
    <Badge variant="secondary" className="text-xs font-normal">
      {route}
    </Badge>
  );
}
