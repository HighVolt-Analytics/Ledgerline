import type { Invoice } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { approvalStatusChipClass, kpiStatusChipClass, needsReviewStatusChipClass } from "@/lib/kpiModuleColors";
import {
  evaluationReviewTooltip,
  evaluationStatusLabel,
} from "@/lib/invoice";
import { cn } from "@/lib/cn";

function evaluationChipClass(status: NonNullable<Invoice["evaluation_status"]>): string {
  switch (status) {
    case "auto_coded":
      return kpiStatusChipClass("green");
    case "vision_vaulted":
      return kpiStatusChipClass("green");
    case "needs_review":
      return needsReviewStatusChipClass();
    case "vision_header_review":
      return needsReviewStatusChipClass();
    case "pending_approval":
      return kpiStatusChipClass("rust");
    case "awaiting_po":
      return kpiStatusChipClass("rose");
    case "awaiting_so":
      return kpiStatusChipClass("rose");
    case "pending_vendor":
      return kpiStatusChipClass("rust");
    case "unmatched_expense_vendor":
      return kpiStatusChipClass("sage");
    default:
      return approvalStatusChipClass("muted");
  }
}

export type EvaluationStatusBadgeInvoice = Pick<
  Invoice,
  | "evaluation_status"
  | "validation_results"
  | "current_stage"
  | "current_stage_state"
  | "document_type_code"
  | "account_code"
  | "account_name"
  | "gl_posting_applicable"
  | "route_target"
  | "llm_suggested_dt"
  | "status"
>;

export function EvaluationStatusBadge({
  status,
  reviewReasons,
  invoice,
}: {
  status: Invoice["evaluation_status"];
  reviewReasons?: string[];
  invoice?: EvaluationStatusBadgeInvoice;
}) {
  const label = status ? evaluationStatusLabel(status, invoice?.route_target) : "—";
  const title = invoice
    ? evaluationReviewTooltip({ ...invoice, evaluation_status: status ?? invoice.evaluation_status }, reviewReasons)
    : evaluationReviewTooltip(
        { evaluation_status: status } as Parameters<typeof evaluationReviewTooltip>[0],
        reviewReasons
      );

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

/** Distinct from evaluation needs_review — ingest T4 weak/unsure duplicate match. */
export function DuplicateReviewBadge({
  suggested,
  className,
}: {
  suggested?: boolean | null;
  className?: string;
}) {
  if (!suggested) return null;
  return (
    <span
      className={cn(needsReviewStatusChipClass(), className)}
      title="Ingest could not strongly confirm uniqueness; a reviewer should check for duplicates."
      data-testid="badge-duplicate-review"
    >
      Possible duplicate — review suggested
    </span>
  );
}
