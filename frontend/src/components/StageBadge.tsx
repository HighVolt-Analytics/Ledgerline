import type { Invoice } from "@/api/types";
import { Loader2 } from "lucide-react";
import type { KpiModuleColor } from "@/lib/kpiModuleColors";
import { approvalStatusChipClass, kpiStatusChipClass } from "@/lib/kpiModuleColors";
import { cn } from "@/lib/cn";

export type PipelineStageState = "done" | "pending" | "fail" | "skipped";

const stageToneByName: Record<string, KpiModuleColor> = {
  Received: "blue",
  Parsed: "teal",
  Validated: "violet",
  Match: "rust",
  Mapped: "green",
  Approved: "sage",
  Processed: "green",
  Posted: "blue",
  Filed: "sage",
  Vaulted: "sage",
  "Header review": "rust",
  Rejected: "rose",
  Duplicate: "rust",
};

function stageChipClass(stage: string, state?: PipelineStageState): string {
  if (/awaiting/i.test(stage)) {
    return kpiStatusChipClass("rose");
  }

  if (state === "skipped") {
    return approvalStatusChipClass("muted");
  }

  const tone = stageToneByName[stage];
  if (tone) {
    return kpiStatusChipClass(tone);
  }

  if (state === "fail") {
    return kpiStatusChipClass("rose");
  }

  return approvalStatusChipClass("muted");
}

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
  title,
}: {
  stage: string;
  state?: PipelineStageState;
  processing?: boolean;
  title?: string;
}) {
  return (
    <span
      className={cn(stageChipClass(stage, state), "inline-flex items-center gap-1")}
      title={title}
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
  inv?: Pick<Invoice, "published_to_ledger" | "evaluation_status">
): string {
  const s = status.toLowerCase();
  if (s === "processed") return inv?.published_to_ledger ? "Posted" : "Processed";
  if (s === "duplicate_skipped") return "Duplicate";
  if (s === "rejected") return "Rejected";
  if (["parsing", "validating"].includes(s)) return "Parsed";
  if (["mapping", "journaling", "reconciling"].includes(s)) return "Mapped";
  if (s === "exception") {
    const evalStatus = (inv?.evaluation_status ?? "").trim();
    if (evalStatus === "vision_vaulted") return "Filed";
    if (evalStatus === "vision_header_review") return "Header review";
    if (evalStatus === "awaiting_classification") return "Parsed";
    return "Validated";
  }
  if (s === "pending") return "Received";
  return "Received";
}

export function invoiceStageBadgeProps(
  inv: Pick<
    Invoice,
    | "status"
    | "current_stage"
    | "current_stage_state"
    | "published_to_ledger"
    | "evaluation_status"
  >
): { stage: string; state?: PipelineStageState } {
  if (inv.current_stage) {
    return {
      stage: invoiceCurrentStage(inv),
      state: invoiceCurrentStageState(inv),
    };
  }
  return { stage: invoiceStage(inv.status, inv) };
}
