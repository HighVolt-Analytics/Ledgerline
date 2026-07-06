import type { Invoice } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { approvalStatusChipClass, kpiStatusChipClass, needsReviewStatusChipClass } from "@/lib/kpiModuleColors";
import {
  evaluationStatusDescription,
  evaluationStatusLabel,
  isNeedsReviewEvaluation,
} from "@/lib/invoice";
import { cn } from "@/lib/cn";

function evaluationChipClass(status: NonNullable<Invoice["evaluation_status"]>): string {
  switch (status) {
    case "auto_coded":
      return kpiStatusChipClass("green");
    case "needs_review":
      return needsReviewStatusChipClass();
    case "awaiting_po":
      return kpiStatusChipClass("rose");
    case "pending_vendor":
      return kpiStatusChipClass("rust");
    case "unmatched_expense_vendor":
      return kpiStatusChipClass("sage");
    default:
      return approvalStatusChipClass("muted");
  }
}

export function EvaluationStatusBadge({
  status,
  reviewReasons,
}: {
  status: Invoice["evaluation_status"];
  reviewReasons?: string[];
}) {
  const label = status ? evaluationStatusLabel(status) : "—";
  const baseTitle = evaluationStatusDescription(status);
  const title =
    reviewReasons?.length && isNeedsReviewEvaluation(status)
      ? `${baseTitle} — ${reviewReasons.join("; ")}`
      : baseTitle;

  if (!status) {
    return (
      <span className="text-muted-foreground text-xs" title={title}>
        —
      </span>
    );
  }

  return (
    <span className={cn(evaluationChipClass(status))} title={title}>
      {label}
    </span>
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
