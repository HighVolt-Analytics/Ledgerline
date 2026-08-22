import type { PipelineActivePath, PipelineAuditStep } from "@/api/types";
import { DossierApprovalPanel } from "@/components/dossiers/DossierApprovalPanel";
import { DossierPipelineStatusKpi } from "@/components/dossiers/DossierPipelineStatusKpi";
import {
  DOSSIER_PIPELINE_FOCUS_STAGE_EVENT,
  DossierPipelineTimeline,
} from "@/components/dossiers/DossierPipelineTimeline";
import { ProcessingStepRunSkipControl } from "@/components/invoices/ProcessingStepRunSkipControl";
import { cn } from "@/lib/cn";
import type { DossierSummaryWithInvoiceId } from "@/lib/dossierApi";
import {
  firstPipelineFailure,
  type DossierPipelineStageId,
} from "@/lib/dossiers";
import {
  PROCESSING_OVERRIDE_STEPS,
  type ProcessingOverrideStepId,
} from "@/lib/processingOverrides";

function pipelineDotClass(state: "done" | "pending" | "fail" | "skipped"): string {
  if (state === "done") return "bg-emerald-500";
  if (state === "fail") return "bg-destructive";
  if (state === "skipped") return "bg-amber-500";
  return "bg-muted-foreground/40";
}

type InvoiceDrawerProcessingSectionProps = {
  dossier: DossierSummaryWithInvoiceId | null;
  dossierLoading: boolean;
  invoicePipelineLoading: boolean;
  invoiceActivePath: PipelineActivePath;
  auditPathTab: "understood" | "not_understood";
  onAuditPathTabChange: (path: "understood" | "not_understood") => void;
  filteredInvoiceSteps: PipelineAuditStep[];
  skipSteps: ProcessingOverrideStepId[];
  overridesEditable: boolean;
  highlightedSkipStepId: ProcessingOverrideStepId | null;
  onToggleSkip?: (stepId: ProcessingOverrideStepId, run: boolean) => void;
};

export function InvoiceDrawerProcessingSection({
  dossier,
  dossierLoading,
  invoicePipelineLoading,
  invoiceActivePath,
  auditPathTab,
  onAuditPathTabChange,
  filteredInvoiceSteps,
  skipSteps,
  overridesEditable,
  highlightedSkipStepId,
  onToggleSkip,
}: InvoiceDrawerProcessingSectionProps) {
  const skipSet = new Set(skipSteps);
  const firstFail = dossier ? firstPipelineFailure(dossier.pipeline) : null;

  return (
    <div className="mt-4 space-y-5" data-testid="invoice-drawer-processing-tab">
      {dossierLoading ? (
        <p className="text-sm text-muted-foreground">Loading processing pipeline…</p>
      ) : dossier ? (
        <div className="space-y-4">
          <DossierPipelineStatusKpi
            dossier={dossier}
            onJumpToFailure={
              firstFail
                ? () => {
                    window.dispatchEvent(
                      new CustomEvent(DOSSIER_PIPELINE_FOCUS_STAGE_EVENT, {
                        detail: { stageId: firstFail.stageId as DossierPipelineStageId },
                      })
                    );
                  }
                : undefined
            }
          />
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Processing pipeline
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              {dossier.pipelinePath === "understood"
                ? "Understood path — capture through vault, then posting stages when continue runs."
                : "Full pipeline from capture through ledger. Expand a stage for checks and evidence."}
            </p>
            <DossierPipelineTimeline
              layout="drawer"
              pipeline={dossier.pipeline}
              routeTarget={dossier.routeTarget}
              pipelinePath={dossier.pipelinePath}
            />
          </div>
          <DossierApprovalPanel
            chain={dossier.approvalChain}
            pipelinePath={dossier.pipelinePath}
          />
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            No posting dossier is linked yet. Showing invoice-level processing stages for this
            document.
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              className="inline-flex rounded-md border border-border p-0.5"
              role="tablist"
              aria-label="Processing path"
            >
              {(
                [
                  ["understood", "Understood"],
                  ["not_understood", "Not understood"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={auditPathTab === value}
                  data-testid={`processing-path-${value}`}
                  onClick={() => onAuditPathTabChange(value)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    auditPathTab === value
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {auditPathTab === "understood"
                ? invoiceActivePath === "understood"
                  ? "Active path — capture → vault, then posting when continue runs."
                  : "Vision path stages (may be inactive for this document)."
                : invoiceActivePath === "not_understood"
                  ? "Active path — OCR / classify → validate → post."
                  : "Legacy OCR path stages (may be inactive for this document)."}
            </p>
          </div>
          {invoicePipelineLoading ? (
            <p className="text-sm text-muted-foreground">Loading processing stages…</p>
          ) : filteredInvoiceSteps.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pipeline stages on this path yet.</p>
          ) : (
            <ol className="relative border-l border-border ml-2 space-y-4">
              {filteredInvoiceSteps.map((step) => (
                <li key={step.stage} className="ml-4">
                  <span
                    className={cn(
                      "absolute -left-[5px] h-2.5 w-2.5 rounded-full",
                      pipelineDotClass(step.state)
                    )}
                  />
                  <div className="text-sm font-medium">{step.stage}</div>
                  <div className="text-xs text-muted-foreground">
                    {step.when} · {step.detail}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <div
        className="border-t border-border pt-4 space-y-3"
        data-testid="processing-reprocess-gates"
      >
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Reprocess gates
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {overridesEditable
              ? "Turn off a gate to skip it on the next Save, Approve, or Reprocess."
              : "Gates that will run or skip on the next reprocess. Click Edit to change them."}
          </p>
        </div>
        <ul className="space-y-2">
          {PROCESSING_OVERRIDE_STEPS.map((step) => {
            const running = !skipSet.has(step.id);
            const highlighted = highlightedSkipStepId === step.id;
            return (
              <li
                key={step.id}
                className={cn(
                  "flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2.5",
                  highlighted && "border-destructive/40 bg-destructive/5"
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground">{step.label}</div>
                  <p className="mt-0.5 text-xs text-muted-foreground">{step.hint}</p>
                  {!running ? (
                    <p className="mt-1 text-xs font-medium ds-warning-text">Skipped on reprocess</p>
                  ) : null}
                </div>
                <ProcessingStepRunSkipControl
                  stepId={step.id}
                  label={step.label}
                  running={running}
                  editable={overridesEditable}
                  highlighted={highlighted}
                  onToggle={onToggleSkip}
                />
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
