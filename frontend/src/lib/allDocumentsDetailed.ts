/**
 * All Documents Detailed column helpers — duplicate, auth, sync, line items.
 */
import type { MatrixRow } from "@/api/types";
import { isInvoicePipelineActive } from "@/lib/uploadColumnState";
import { pillTones } from "@/components/StatusPill";

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

export function lineItemCellValue(
  row: MatrixRow,
  count?: number | null
): string {
  const n = count ?? row.line_item_count ?? 0;
  if (n > 0) return String(n);
  if (isInvoicePipelineActive(row.invoice)) return "—";
  return "0";
}

export function normalizeAuthSyncLabel(raw: string | null | undefined): AuthSyncLabel {
  const token = (raw ?? "").trim();
  if (!token || token === "—" || token === "-") return "—";
  return token;
}

export function authSyncPillClass(label: AuthSyncLabel): string {
  if (label === "Done" || label === "Synced") return pillTones.ok;
  if (label === "Failed") return pillTones.bad;
  if (label === "Pending") return pillTones.amber;
  return pillTones.muted;
}
