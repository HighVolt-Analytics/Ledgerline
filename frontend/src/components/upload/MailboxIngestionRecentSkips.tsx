import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import { cn } from "@/lib/cn";

type MailboxIngestionRecentSkipsProps = {
  mailboxEmail: string;
  compact?: boolean;
};

export function MailboxIngestionRecentSkips({
  mailboxEmail,
  compact = true,
}: MailboxIngestionRecentSkipsProps) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useTenantQuery({
    queryKey: [...queryKeys.emailIngestionRules(), "recent-skips", mailboxEmail],
    queryFn: () => api.getEmailIngestionRecentSkips(mailboxEmail),
    enabled: open,
  });

  const skips = data?.skips ?? [];

  return (
    <div
      className={cn("rounded-md border border-border bg-muted/10", compact ? "p-2" : "p-3")}
      data-testid={`mailbox-recent-skips-${mailboxEmail}`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        Recently skipped
        {open && !isLoading ? ` (${skips.length})` : null}
      </button>
      {open ? (
        <div className="mt-2 space-y-1.5">
          {isLoading ? (
            <p className="text-[11px] text-muted-foreground">Loading recent skips…</p>
          ) : skips.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">No skipped emails recorded for this mailbox.</p>
          ) : (
            skips.map((row) => (
              <p
                key={`${row.message_id ?? row.timestamp}-${row.attachment}-${row.sender}`}
                className="text-[11px] leading-snug text-foreground/90"
              >
                <span className="font-mono">{row.attachment || "attachment"}</span>
                {" from "}
                <span className="font-mono">{row.sender || "unknown sender"}</span>
                {" — "}
                {row.reason_label}
                {row.capture_rule_name ? ` (${row.capture_rule_name})` : null}
                {row.relative_time ? ` (${row.relative_time})` : null}
              </p>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
