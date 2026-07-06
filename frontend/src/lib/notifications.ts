import type { LucideIcon } from "lucide-react";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { NotificationSeverity } from "@/api/types";

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
