import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import type { AuditLogEntry } from "@/api/types";
import {
  formatBankAuditDetail,
  formatBankAuditEvent,
} from "@/lib/bankFeedCopy";
import { cn } from "@/lib/cn";

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Collapsible audit list — same interaction pattern as DocumentAuditTrail. */
export function BankFeedTxnAuditTrail({
  entries,
  loading,
  error,
}: {
  entries: AuditLogEntry[];
  loading: boolean;
  error: string | null;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="mt-4 border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        data-testid="bank-txn-audit-toggle"
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <FileText className="h-3.5 w-3.5" />
        Audit Trail ({loading ? "…" : entries.length})
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 max-h-56 overflow-y-auto">
          {loading && (
            <p className="text-xs text-muted-foreground pl-5">Loading audit trail…</p>
          )}
          {error && <p className="text-xs text-destructive pl-5">{error}</p>}
          {!loading && !error && entries.length === 0 && (
            <p className="text-xs text-muted-foreground pl-5">
              No events recorded for this transaction.
            </p>
          )}
          {entries.map((entry) => (
            <div key={entry.id} className="flex items-start gap-2 text-[11px] pl-5">
              <span className="tnum text-muted-foreground whitespace-nowrap">
                {formatWhen(entry.created_at)}
              </span>
              <span className={cn("font-medium whitespace-nowrap text-foreground")}>
                {formatBankAuditEvent(entry.event)}
              </span>
              <span className="text-muted-foreground">
                {formatBankAuditDetail(entry.detail)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
