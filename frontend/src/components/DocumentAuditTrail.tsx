import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { auditForDoc } from "@/lib/v4MockData";
import { cn } from "@/lib/cn";

export function DocumentAuditTrail({ docId }: { docId: string }) {
  const [open, setOpen] = useState(false);
  const events = auditForDoc(docId);

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
        Audit Trail ({events.length})
      </button>
      {open && (
        <div className="mt-2 space-y-1.5">
          {events.length === 0 && (
            <p className="text-xs text-muted-foreground pl-5">No events recorded for this document.</p>
          )}
          {events.map((e) => (
            <div key={e.id} className="flex items-start gap-2 text-[11px] pl-5">
              <span className="tnum text-muted-foreground whitespace-nowrap">{e.ts}</span>
              <span
                className={cn(
                  "font-medium whitespace-nowrap",
                  e.action === "Paid" || e.action === "Approved" || e.action === "Posted"
                    ? "text-primary"
                    : e.action === "Rejected" || e.action === "Flagged"
                      ? "text-destructive"
                      : "text-foreground"
                )}
              >
                {e.action}
              </span>
              <span className="text-muted-foreground">{e.detail}</span>
              <span className="ml-auto text-muted-foreground whitespace-nowrap">{e.actor}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
