import { useState } from "react";
import { Calendar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTenantTime } from "@/hooks/useTenantTime";
import { cn } from "@/lib/cn";
import { shiftDateOnly, tenantTodayIso } from "@/lib/tenantTime";

export function MailboxImportDialog({
  open,
  mailboxEmail,
  busy,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mailboxEmail: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    from_date: string;
    to_date: string;
    mark_processed: boolean;
  }) => void;
}) {
  const { timeZone } = useTenantTime();
  const today = tenantTodayIso(timeZone);
  const [fromDate, setFromDate] = useState(() => shiftDateOnly(today, -30));
  const [toDate, setToDate] = useState(() => today);
  const [markProcessed, setMarkProcessed] = useState(false);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mailbox-import-title"
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-background p-5 shadow-lg">
        <h2 id="mailbox-import-title" className="text-sm font-semibold mb-1">
          Import historical mail
        </h2>
        <p className="text-xs text-muted-foreground mb-4">
          Import messages with attachments from{" "}
          <span className="font-medium text-foreground">{mailboxEmail}</span> between
          the selected dates. Read and unread messages are included. Only attachments
          matching your ingestion rules are accepted into the pipeline.
        </p>

        <div className="grid gap-3 sm:grid-cols-2 mb-4">
          <label className="text-xs space-y-1">
            <span className="text-muted-foreground">From</span>
            <Input
              type="date"
              value={fromDate}
              max={toDate}
              onChange={(e) => setFromDate(e.target.value)}
              data-testid="input-import-from-date"
            />
          </label>
          <label className="text-xs space-y-1">
            <span className="text-muted-foreground">To</span>
            <Input
              type="date"
              value={toDate}
              min={fromDate}
              max={today}
              onChange={(e) => setToDate(e.target.value)}
              data-testid="input-import-to-date"
            />
          </label>
        </div>

        <label className="flex items-start gap-2 text-xs mb-4 cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={markProcessed}
            onChange={(e) => setMarkProcessed(e.target.checked)}
            data-testid="checkbox-mark-processed"
          />
          <span>
            Mark imported emails as read / move to Processed when attachments are
            successfully ingested
          </span>
        </label>

        <div className="flex flex-wrap gap-2 justify-end">
          <Button variant="outline" size="sm" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={busy || !fromDate || !toDate}
            data-testid="button-start-import"
            onClick={() =>
              onSubmit({
                from_date: fromDate,
                to_date: toDate,
                mark_processed: markProcessed,
              })
            }
          >
            <Calendar className={cn("h-3.5 w-3.5 mr-1", busy && "animate-pulse")} />
            {busy ? "Importing…" : "Start import"}
          </Button>
        </div>
      </div>
    </div>
  );
}
