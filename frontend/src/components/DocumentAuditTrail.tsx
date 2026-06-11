import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { api } from "@/api/client";
import type { PipelineAuditStep } from "@/api/types";
import { cn } from "@/lib/cn";

function pipelineActionClass(state: PipelineAuditStep["state"]): string {
  if (state === "done") return "text-primary";
  if (state === "fail") return "text-destructive";
  return "text-foreground";
}

export function DocumentAuditTrail({
  docId,
  invoiceId,
}: {
  docId: string;
  invoiceId?: number;
}) {
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<PipelineAuditStep[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || invoiceId == null) return;
    setLoading(true);
    setError(null);
    api
      .getInvoicePipeline(invoiceId, { fresh: true })
      .then(setSteps)
      .catch(() => {
        setSteps([]);
        setError("Could not load audit trail.");
      })
      .finally(() => setLoading(false));
  }, [open, invoiceId]);

  const eventCount = invoiceId != null ? steps.length : 0;

  return (
    <div className="mt-4 border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        data-testid={`audit-toggle-${docId}`}
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <FileText className="h-3.5 w-3.5" />
        Audit Trail ({loading ? "…" : eventCount})
      </button>
      {open && (
        <div className="mt-2 space-y-1.5">
          {loading && (
            <p className="text-xs text-muted-foreground pl-5">Loading audit trail…</p>
          )}
          {error && <p className="text-xs text-destructive pl-5">{error}</p>}
          {!loading && invoiceId != null && steps.length === 0 && !error && (
            <p className="text-xs text-muted-foreground pl-5">No events recorded for this document.</p>
          )}
          {!loading && invoiceId == null && (
            <p className="text-xs text-muted-foreground pl-5">No events recorded for this document.</p>
          )}
          {invoiceId != null &&
            steps.map((step, idx) => (
              <div key={`${step.stage}-${idx}`} className="flex items-start gap-2 text-[11px] pl-5">
                <span className="tnum text-muted-foreground whitespace-nowrap">{step.when}</span>
                <span className={cn("font-medium whitespace-nowrap", pipelineActionClass(step.state))}>
                  {step.stage}
                </span>
                <span className="text-muted-foreground">{step.detail}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
