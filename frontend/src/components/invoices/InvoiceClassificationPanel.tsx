import type { InvoiceClassificationAudit } from "@/api/types";
import {
  autoRouteThresholdSummary,
  classificationReviewReasons,
  classificationStatusMessage,
  formatClassificationConfidence,
  formatDtCodeWithName,
  reviewReasonLabel,
} from "@/lib/classificationAuditDisplay";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

type InvoiceClassificationPanelProps = {
  audit: InvoiceClassificationAudit | null;
  loading?: boolean;
  requiresConfirm?: boolean;
  onConfirmDt?: (code: string) => void;
  onChangeDt?: (code: string) => void;
  catalogueCodes?: string[];
  documentTypes?: DocumentTypeDefinition[];
};

export function InvoiceClassificationPanel({
  audit,
  loading,
  requiresConfirm = false,
  onConfirmDt,
  onChangeDt,
  catalogueCodes = [],
  documentTypes = [],
}: InvoiceClassificationPanelProps) {
  if (loading) {
    return (
      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Loading classification…
      </div>
    );
  }
  if (!audit) {
    return null;
  }

  const llmDt = audit.llm_suggested_dt ?? "";
  const policyDt = audit.policy_winner_dt ?? "";
  const confirmed = audit.confirmed_dt ?? audit.document_type_code ?? "";
  const chips = classificationReviewReasons(audit);
  const statusMessage = classificationStatusMessage(audit);
  const thresholdSummary = autoRouteThresholdSummary(audit);
  const showActions =
    requiresConfirm && Boolean(onConfirmDt || onChangeDt) && catalogueCodes.length > 0;

  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-2.5 text-xs space-y-3">
      <div className="font-medium text-foreground">AI classification</div>

      {thresholdSummary ? (
        <p className="text-muted-foreground">{thresholdSummary}</p>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-3">
        <div className="rounded border border-border/60 bg-background/50 p-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">LLM suggested</div>
          <div className="mt-1 font-medium text-foreground">
            {formatDtCodeWithName(documentTypes, llmDt)}
          </div>
          <div className="text-muted-foreground tnum">{formatClassificationConfidence(audit.llm_confidence)}</div>
        </div>
        <div className="rounded border border-border/60 bg-background/50 p-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Policy winner</div>
          <div className="mt-1 font-medium text-foreground">
            {formatDtCodeWithName(documentTypes, policyDt)}
          </div>
          <div className="text-muted-foreground tnum">
            {formatClassificationConfidence(audit.policy_winner_confidence)}
          </div>
        </div>
        <div className="rounded border border-border/60 bg-background/50 p-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Confirmed</div>
          <div className="mt-1 font-medium text-foreground">
            {formatDtCodeWithName(documentTypes, confirmed)}
          </div>
          <div className="text-muted-foreground tnum">
            {formatClassificationConfidence(audit.confirmed_confidence ?? audit.document_type_confidence)}
          </div>
        </div>
      </div>

      {audit.llm_reasoning ? (
        <p className="text-muted-foreground">{audit.llm_reasoning}</p>
      ) : audit.reason ? (
        <p className="text-muted-foreground">{audit.reason}</p>
      ) : null}

      {chips.length ? (
        <div className="space-y-1.5">
          <p className="text-amber-800 dark:text-amber-300">
            {requiresConfirm
              ? "Confirm or change document type to continue processing."
              : "Classification review notes:"}
          </p>
          <div className="flex flex-wrap gap-1">
            {chips.map((chip) => (
              <span
                key={chip}
                title={chip}
                className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-800 dark:text-amber-300"
              >
                {reviewReasonLabel(chip)}
              </span>
            ))}
          </div>
        </div>
      ) : statusMessage ? (
        <p className="text-emerald-700 dark:text-emerald-400">{statusMessage}</p>
      ) : null}

      {showActions ? (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {onConfirmDt && llmDt ? (
            <button
              type="button"
              className="rounded-md border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted"
              onClick={() => onConfirmDt(llmDt)}
            >
              Confirm {formatDtCodeWithName(documentTypes, llmDt)}
            </button>
          ) : null}
          {onChangeDt ? (
            <select
              className="rounded-md border border-border bg-background px-2 py-1 text-[11px]"
              defaultValue=""
              onChange={(e) => {
                const code = e.target.value;
                if (code) onChangeDt(code);
              }}
            >
              <option value="" disabled>
                Change DT…
              </option>
              {catalogueCodes.map((code) => (
                <option key={code} value={code}>
                  {formatDtCodeWithName(documentTypes, code)}
                </option>
              ))}
            </select>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
