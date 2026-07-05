import type { Invoice } from "@/api/types";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type PipelineStageState = "done" | "pending" | "fail" | "skipped";

const stylesByState: Record<PipelineStageState, string> = {
  done: "bg-primary/15 text-primary",
  pending: "bg-[hsl(43_74%_49%/0.18)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]",
  fail: "bg-destructive/15 text-destructive",
  skipped: "bg-muted text-muted-foreground",
};

const stylesByStage: Record<string, string> = {
  Received: "bg-muted text-muted-foreground",
  Parsed: "bg-[hsl(var(--chart-3)/0.15)] text-[hsl(var(--chart-3))]",
  Validated: "bg-[hsl(var(--chart-3)/0.15)] text-[hsl(var(--chart-3))]",
  Mapped: "bg-accent text-accent-foreground",
  Approved: "bg-primary/15 text-primary",
  Processed: "bg-primary/15 text-primary",
  Posted: "bg-primary text-primary-foreground",
  Rejected: "bg-destructive/15 text-destructive",
  Duplicate: "bg-destructive/15 text-destructive",
};

export function invoiceCurrentStage(inv: Pick<Invoice, "current_stage">): string {
  return inv.current_stage?.trim() || "Received";
}

export function invoiceCurrentStageState(
  inv: Pick<Invoice, "current_stage_state">
): PipelineStageState {
  const state = inv.current_stage_state;
  if (state === "done" || state === "pending" || state === "fail" || state === "skipped") {
    return state;
  }
  return "pending";
}

export function StageBadge({
  stage,
  state,
  processing = false,
}: {
  stage: string;
  state?: PipelineStageState;
  processing?: boolean;
}) {
  const className =
    (state && stylesByState[state]) ||
    stylesByStage[stage] ||
    "bg-muted text-muted-foreground";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        className
      )}
    >
      {processing ? (
        <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden />
      ) : null}
      {stage}
    </span>
  );
}

/** Status-only fallback when pipeline fields are unavailable (legacy lists). */
export function invoiceStage(
  status: string,
  inv?: Pick<Invoice, "published_to_ledger">
): string {
  const s = status.toLowerCase();
  if (s === "processed") return inv?.published_to_ledger ? "Posted" : "Processed";
  if (s === "duplicate_skipped") return "Duplicate";
  if (s === "rejected") return "Rejected";
  if (["parsing", "validating"].includes(s)) return "Parsed";
  if (["mapping", "journaling", "reconciling"].includes(s)) return "Mapped";
  if (s === "exception") return "Validated";
  if (s === "pending") return "Received";
  return "Received";
}

export function invoiceStageBadgeProps(
  inv: Pick<Invoice, "status" | "current_stage" | "current_stage_state" | "published_to_ledger">
): { stage: string; state?: PipelineStageState } {
  if (inv.current_stage) {
    return {
      stage: invoiceCurrentStage(inv),
      state: invoiceCurrentStageState(inv),
    };
  }
  return { stage: invoiceStage(inv.status, inv) };
}
