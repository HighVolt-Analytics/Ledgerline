/**
 * All Documents Detailed column helpers — duplicate, auth, sync.
 */
import type { MatrixRow } from "@/api/types";
import { cn } from "@/lib/cn";
import { approvalStatusChipClass, kpiStatusChipClass } from "@/lib/kpiModuleColors";

export type AuthSyncLabel = "Done" | "Pending" | "Failed" | "Synced" | "—" | string;

export function duplicateCellValue(row: MatrixRow): {
  label: string;
  kind: "conflict" | "possible" | "empty";
} {
  const conflict = (row.conflict_with ?? "").trim();
  if (conflict) return { label: conflict, kind: "conflict" };
  if (row.invoice.duplicate_review_suggested) {
    return { label: "Possible", kind: "possible" };
  }
  return { label: "—", kind: "empty" };
}

/** Documents that belong in Upload Notifications — not the main documents table. */
export function isDuplicateNotificationRow(row: MatrixRow): boolean {
  const inv = row.invoice;
  if (inv.status === "duplicate_skipped") return true;
  if (inv.duplicate_review_suggested) return true;
  if ((row.flag ?? "").trim() === "Duplicate Suspected") return true;
  if ((row.conflict_with ?? "").trim()) return true;
  return false;
}

export function duplicateNotificationCopy(row: MatrixRow): {
  title: string;
  detail: string;
} {
  const dup = duplicateCellValue(row);
  const reason = (row.flag_reason ?? "").trim();
  if (dup.kind === "conflict") {
    return {
      title: "Duplicate conflict",
      detail: reason || `Conflicts with ${dup.label}`,
    };
  }
  if (
    row.invoice.status === "duplicate_skipped" ||
    (row.flag ?? "").trim() === "Duplicate Suspected"
  ) {
    return {
      title: "Duplicate detected",
      detail: reason || "This document was skipped as a duplicate — review to confirm",
    };
  }
  return {
    title: "Possible duplicate",
    detail: reason || "Review suggested — confirm unique or mark as duplicate",
  };
}

export function normalizeAuthSyncLabel(raw: string | null | undefined): AuthSyncLabel {
  const token = (raw ?? "").trim();
  if (!token || token === "—" || token === "-") return "—";
  return token;
}

export function authSyncPillClass(label: AuthSyncLabel): string {
  if (label === "Done" || label === "Synced") {
    return cn(kpiStatusChipClass("green"), "!rounded-full");
  }
  if (label === "Failed") return cn(approvalStatusChipClass("reject"), "!rounded-full");
  if (label === "Pending") return cn(approvalStatusChipClass("pending"), "!rounded-full");
  return cn(approvalStatusChipClass("muted"), "!rounded-full");
}
