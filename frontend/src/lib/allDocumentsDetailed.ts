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
