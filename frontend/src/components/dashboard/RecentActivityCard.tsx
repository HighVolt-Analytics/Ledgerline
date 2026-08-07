import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";
import { kpiModuleFill, type KpiModuleColor } from "@/lib/kpiModuleColors";
import { vaultInvoiceLink } from "@/lib/vault";

export type RecentActivityItem = {
  id: string;
  invoiceId: number | null;
  event: string;
  documentRef: string | null;
  vendor: string | null;
  summary: string | null;
  time: string;
};

type ActionMeta = { label: string; tone: KpiModuleColor };

function actionMeta(event: string, summary?: string | null): ActionMeta {
  if (summary?.trim()) {
    return { label: summary.trim(), tone: "blue" };
  }
  if (event === "duplicate_skipped" || event === "duplicate_in_progress") {
    return { label: "Duplicate flagged", tone: "rust" };
  }
  if (event === "duplicate_reingest_rejected") {
    return { label: "Resubmitted", tone: "violet" };
  }
  if (event.includes("validation_failed") || event.includes("parsing_failed")) {
    return { label: "Validation failed", tone: "rose" };
  }
  if (event.includes("processed")) {
    return { label: "Posted to ledger", tone: "green" };
  }
  if (event.includes("approved") || event === "payment_approved") {
    return { label: "Approved", tone: "teal" };
  }
  if (event.includes("upload")) {
    return { label: "Uploaded", tone: "cyan" };
  }
  if (event.includes("email") || event.includes("ingest") || event.includes("poll")) {
    return { label: "Captured", tone: "blue" };
  }
  if (event.includes("blocked") || event.includes("error") || event === "low_credits") {
    return { label: "Blocked", tone: "rose" };
  }
  if (event.includes("connected")) {
    return { label: "Connected", tone: "green" };
  }
  if (event.includes("disconnected")) {
    return { label: "Disconnected", tone: "rust" };
  }
  if (event.includes("payment")) {
    return { label: "Payment update", tone: "violet" };
  }
  const words = event.replace(/_/g, " ").trim();
  return {
    label: words.replace(/\b\w/g, (c) => c.toUpperCase()),
    tone: "sage",
  };
}

function primaryLine(item: RecentActivityItem, action: string): string {
  const doc = item.documentRef?.trim();
  const vendor = item.vendor?.trim();
  if (doc && vendor) return `${doc} · ${vendor} — ${action}`;
  if (doc) return `${doc} — ${action}`;
  if (vendor) return `${vendor} — ${action}`;
  return action;
}

export function RecentActivityCard({
  items,
  className,
}: {
  items: RecentActivityItem[];
  className?: string;
}) {
  const { theme } = useTheme();

  return (
    <Card
      className={cn("dash-card--elevated p-4", className)}
      data-testid="dashboard-recent-activity"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Recent activity</h3>
        {items.length > 0 ? (
          <span className="text-xs tnum tabular-nums text-muted-foreground">
            {items.length}
          </span>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No recent events.</p>
      ) : (
        <ul className="space-y-0.5" data-testid="recent-activity-list">
          {items.map((item) => {
            const action = actionMeta(item.event, item.summary);
            const label = primaryLine(item, action.label);
            const fill = kpiModuleFill(action.tone, theme);

            const rowClass = cn(
              "flex items-start gap-2.5 rounded-md px-1.5 py-1.5 text-sm",
              "hover:bg-muted/45 transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            );

            const content = (
              <>
                <span
                  className="mt-1.5 h-2 w-2 shrink-0 rounded-full self-start"
                  style={{ backgroundColor: fill }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 break-words font-medium text-foreground leading-snug">
                  {label}
                </span>
                <time className="shrink-0 self-start pt-0.5 text-xs tnum tabular-nums text-muted-foreground">
                  {item.time}
                </time>
              </>
            );

            return (
              <li key={item.id}>
                {item.invoiceId != null ? (
                  <Link
                    to={vaultInvoiceLink(item.invoiceId)}
                    title="Open document in Vault"
                    className={rowClass}
                  >
                    {content}
                  </Link>
                ) : (
                  <div className={rowClass}>{content}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
