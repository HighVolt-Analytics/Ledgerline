import type { Invoice } from "@/api/types";
import { invId } from "@/lib/format";
import { invoiceRoutedToSuspense } from "@/lib/matrix";
import { cn } from "@/lib/cn";

/** v4 kanban column per demo document (`xA` in v4 bundle). */
const V4_INBOX_KANBAN: Record<string, "pending" | "awaiting" | "approved" | "rejected"> = {
  "INV-001": "approved",
  "INV-002": "pending",
  "INV-003": "awaiting",
  "INV-004": "awaiting",
  "INV-005": "approved",
  "INV-006": "pending",
  "INV-007": "pending",
  "INV-008": "awaiting",
  "INV-009": "rejected",
  "INV-010": "pending",
};

const styles: Record<string, string> = {
  Received: "bg-muted text-muted-foreground",
  Parsed: "bg-[hsl(var(--chart-3)/0.15)] text-[hsl(var(--chart-3))]",
  Validated: "bg-[hsl(var(--chart-3)/0.15)] text-[hsl(var(--chart-3))]",
  Mapped: "bg-accent text-accent-foreground",
  "Awaiting Approval": "bg-[hsl(43_74%_49%/0.18)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]",
  Approved: "bg-primary/15 text-primary",
  Published: "bg-primary text-primary-foreground",
  Rejected: "bg-destructive/15 text-destructive",
  Suspense: "bg-destructive/15 text-destructive",
  Exception: "bg-destructive/15 text-destructive",
};

export function StageBadge({ stage }: { stage: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        styles[stage] ?? "bg-muted text-muted-foreground"
      )}
    >
      {stage}
    </span>
  );
}

export function invoiceStage(status: string): string {
  const s = status.toLowerCase();
  if (s === "processed") return "Published";
  if (s === "exception") return "Suspense";
  if (s === "duplicate_skipped") return "Rejected";
  if (s === "rejected") return "Rejected";
  if (["parsing", "validating"].includes(s)) return "Parsed";
  if (["mapping", "journaling", "reconciling"].includes(s)) return "Mapped";
  if (s === "pending") return "Received";
  return "Received";
}

/** Inbox table stage — matches v4 `M()` / `pde`. */
export function inboxStage(inv: Invoice): string {
  if (inv.status === "processed") return "Published";

  const kanban = V4_INBOX_KANBAN[invId(inv.id)];
  if (kanban === "approved") return "Approved";
  if (kanban === "rejected") return "Rejected";
  if (kanban === "awaiting") return "Awaiting Approval";

  if (invoiceRoutedToSuspense(inv) || inv.status === "exception") return "Suspense";
  if (inv.status === "duplicate_skipped" || inv.status === "rejected") return "Rejected";
  if (inv.status === "journaling" || inv.status === "reconciling") return "Awaiting Approval";

  return "Mapped";
}
