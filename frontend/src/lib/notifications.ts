import type { LucideIcon } from "lucide-react";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { NotificationSeverity } from "@/api/types";
import { formatUploadedAt } from "@/lib/allDocumentsSummary";

export function activityLabel(
  event: string,
  vendor: string | null,
  documentRef: string | null,
  summary?: string | null
): string {
  const id = documentRef?.trim() || "System";
  const who = vendor ?? "Unknown vendor";
  const label = `${id} · ${who}`;

  if (summary?.trim()) {
    return `${label} — ${summary.trim()}`;
  }
  if (event === "duplicate_skipped") {
    return `${label} duplicate skipped`;
  }
  if (event === "duplicate_in_progress") {
    return `${label} duplicate blocked (still processing)`;
  }
  if (event === "duplicate_reingest_rejected") {
    return `${label} resubmitted after rejection`;
  }
  if (event.includes("validation_failed") || event.includes("parsing_failed")) {
    return `${label} validation failed`;
  }
  if (event.includes("processed")) {
    return `${label} posted to ledger`;
  }
  if (event.includes("approved")) {
    return `${label} approved for reprocessing`;
  }
  if (event.includes("upload")) {
    return `${label} captured via upload`;
  }
  if (event.includes("email") || event.includes("ingest") || event.includes("poll")) {
    return `${label} captured via email`;
  }
  if (event === "stripe_account_connected_onboarding") {
    return "Stripe account connected (onboarding)";
  }
  if (event === "stripe_account_connected_oauth") {
    return "Stripe account connected (OAuth)";
  }
  if (event === "stripe_account_disconnected") {
    return "Stripe account disconnected";
  }
  if (event === "stripe_status_refreshed") {
    return "Stripe account status refreshed";
  }
  if (event === "vendor_payout_method_created") {
    return "Vendor payout method added";
  }
  if (event === "vendor_payout_method_updated") {
    return "Vendor payout method updated";
  }
  if (event === "vendor_payout_method_deleted") {
    return "Vendor payout method removed";
  }
  if (event === "payment_execution_readiness_validated") {
    return "Payment execution readiness validated (dry-run)";
  }
  if (event === "payment_approved") {
    return "Payment approved for disbursement readiness";
  }
  if (event === "payment_execution_instruction_created") {
    return "Manual payment instruction created";
  }
  if (event === "payment_marked_paid_manual") {
    return "Payment marked paid manually (no funds moved)";
  }
  if (event === "low_credits") {
    return "Credits running low";
  }
  if (event === "accounting_integration_connected") {
    return "Accounting integration connected";
  }
  if (event === "accounting_integration_disconnected") {
    return "Accounting integration disconnected";
  }
  if (event === "accounting_integration_error") {
    return "Accounting integration error";
  }
  if (event === "payment_execution_blocked_by_safety_gate") {
    return "Payment execution blocked by safety gate";
  }
  if (event === "payment_execution_blocked_by_tenant_disable") {
    return "Payment execution blocked for tenant";
  }
  if (event === "payment_execution_blocked_by_limit") {
    return "Payment execution blocked — over launch limit";
  }
  return `${label} — ${event.replace(/_/g, " ")}`;
}

export function relativeNotificationTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function notificationSeverityIcon(severity: NotificationSeverity): LucideIcon {
  if (severity === "error") return AlertTriangle;
  if (severity === "action") return AlertTriangle;
  if (severity === "info") return CheckCircle2;
  return Info;
}

export function notificationSeverityClass(severity: NotificationSeverity): string {
  if (severity === "error") return "text-destructive";
  if (severity === "action") return "text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]";
  return "text-muted-foreground";
}

export function formatUnreadBadge(count: number): string {
  if (count <= 0) return "";
  if (count > 9) return "9+";
  return String(count);
}

const DUPLICATE_FILE_EVENTS = new Set([
  "duplicate_skipped",
  "duplicate_in_progress",
  "duplicate_reingest_rejected",
]);

export function isDuplicateFileNotificationEvent(event: string | null | undefined): boolean {
  return DUPLICATE_FILE_EVENTS.has((event ?? "").trim());
}

export type NotificationDayGroup = "Today" | "Yesterday" | "Earlier";

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function notificationDayGroup(iso: string | null | undefined): NotificationDayGroup {
  if (!iso) return "Earlier";
  const created = new Date(iso);
  if (Number.isNaN(created.getTime())) return "Earlier";
  const day = startOfLocalDay(created);
  const today = startOfLocalDay(new Date());
  const dayMs = 24 * 60 * 60 * 1000;
  if (day === today) return "Today";
  if (day === today - dayMs) return "Yesterday";
  return "Earlier";
}

export function groupNotificationsByDay<T extends { created_at: string }>(
  items: T[]
): { label: NotificationDayGroup; items: T[] }[] {
  const buckets: Record<NotificationDayGroup, T[]> = {
    Today: [],
    Yesterday: [],
    Earlier: [],
  };
  for (const item of items) {
    buckets[notificationDayGroup(item.created_at)].push(item);
  }
  return (["Today", "Yesterday", "Earlier"] as const)
    .filter((label) => buckets[label].length > 0)
    .map((label) => ({ label, items: buckets[label] }));
}

/** Display as `dd/mm/yy/hh:mm` in the viewer's local timezone. */
export function formatNotificationTimestamp(iso: string | null | undefined): string {
  return formatUploadedAt(iso);
}

const EVENT_CARD: Record<
  string,
  { issue: string; category: string; status: string | null }
> = {
  unmatched_team_vendor: {
    issue: "Unmatched team vendor",
    category: "Vendor matching",
    status: "Needs review",
  },
  unmatched_expense_vendor: {
    issue: "Unmatched expense vendor",
    category: "Vendor matching",
    status: "Needs review",
  },
  vendor_registration_hold: {
    issue: "Vendor not registered",
    category: "Vendor matching",
    status: "Needs review",
  },
  customer_registration_hold: {
    issue: "Customer not registered",
    category: "Customer matching",
    status: "Needs review",
  },
  team_expense_approval_required: {
    issue: "Approval required",
    category: "Team expense",
    status: "Needs review",
  },
  purchase_awaiting_po: {
    issue: "Awaiting purchase order",
    category: "Purchase",
    status: "Needs review",
  },
  validation_failed: {
    issue: "Validation failed",
    category: "Capture",
    status: "Needs review",
  },
  pipeline_error: {
    issue: "Pipeline error",
    category: "Processing",
    status: "Failed",
  },
  invoice_rejected: {
    issue: "Invoice rejected",
    category: "Approval",
    status: "Rejected",
  },
  invoice_approved: {
    issue: "Invoice approved",
    category: "Approval",
    status: "Approved",
  },
  invoice_processed: {
    issue: "Posted to ledger",
    category: "Pipeline",
    status: "Done",
  },
  duplicate_skipped: {
    issue: "Duplicate detected",
    category: "Duplicate",
    status: "Needs review",
  },
  duplicate_in_progress: {
    issue: "Duplicate blocked",
    category: "Duplicate",
    status: "Needs review",
  },
  duplicate_review_suggested: {
    issue: "Possible duplicate",
    category: "Duplicate",
    status: "Needs review",
  },
  duplicate_reingest_rejected: {
    issue: "Resubmitted after rejection",
    category: "Duplicate",
    status: "Needs review",
  },
  email_ingested: {
    issue: "Captured via email",
    category: "Email",
    status: null,
  },
  low_credits: {
    issue: "Credits running low",
    category: "Billing",
    status: "Needs review",
  },
  accounting_integration_error: {
    issue: "Accounting integration error",
    category: "Integrations",
    status: "Failed",
  },
  accounting_integration_disconnected: {
    issue: "Accounting integration disconnected",
    category: "Integrations",
    status: "Failed",
  },
  payment_execution_blocked_by_safety_gate: {
    issue: "Payment blocked by safety gate",
    category: "Payments",
    status: "Failed",
  },
  payment_execution_blocked_by_tenant_disable: {
    issue: "Payment blocked for tenant",
    category: "Payments",
    status: "Failed",
  },
  payment_execution_blocked_by_limit: {
    issue: "Payment blocked — over limit",
    category: "Payments",
    status: "Failed",
  },
};

export type NotificationCardFields = {
  documentRef: string;
  party: string | null;
  issue: string;
  category: string | null;
  status: string | null;
  when: string;
};

export function notificationCardFields(item: {
  title: string;
  summary: string | null;
  event: string;
  created_at: string;
}): NotificationCardFields {
  const mapped = EVENT_CARD[item.event];
  const beforeDash = item.title.split(" — ")[0]?.trim() || item.title;
  const hasParty = beforeDash.includes(" · ");
  const [refPart, partyPart] = beforeDash.split(" · ");
  const systemTitle = Boolean(mapped && !hasParty && beforeDash === mapped.issue);

  return {
    documentRef: systemTitle ? "System" : (refPart || "").trim() || "System",
    party: hasParty ? (partyPart || "").trim() || null : null,
    issue:
      mapped?.issue ??
      item.summary?.trim() ??
      item.title.split(" — ")[1]?.trim() ??
      item.event.replace(/_/g, " "),
    category: mapped?.category ?? null,
    status: mapped?.status ?? null,
    when: formatNotificationTimestamp(item.created_at),
  };
}
