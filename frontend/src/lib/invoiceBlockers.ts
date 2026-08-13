import type { Invoice } from "@/api/types";
import { normalizeCurrencyCode } from "@/lib/format";

export type InvoiceBlockerKey = "currency" | "total" | "vendor";

/** True when currency is a valid ISO 4217 alpha-3 code (same rule as drawer). */
export function isInvoiceCurrencySet(currency: string | null | undefined): boolean {
  const code = normalizeCurrencyCode(currency);
  return Boolean(code && /^[A-Z]{3}$/.test(code));
}

function isTotalPresent(total: string | null | undefined): boolean {
  const raw = (total ?? "").trim();
  return Boolean(raw && !Number.isNaN(Number(raw)) && Number(raw) > 0);
}

/**
 * Detect missing Fields blockers from list-level invoice fields.
 * When the DT lists extraction fields, only those keys can block (no hardcoded vendor).
 * Suspense GL is intentionally not a blocker here — call sites check it after fields.
 */
export function detectInvoiceBlockers(
  inv: Pick<
    Invoice,
    "currency" | "total" | "vendor" | "evaluation_status" | "document_type_extraction_fields"
  >
): InvoiceBlockerKey[] {
  const configured = (inv.document_type_extraction_fields ?? [])
    .map((key) => key.trim().toLowerCase())
    .filter(Boolean);
  const inScope = (key: InvoiceBlockerKey) => configured.includes(key);
  const blockers: InvoiceBlockerKey[] = [];
  if (inScope("currency") && !isInvoiceCurrencySet(inv.currency)) blockers.push("currency");
  if (inScope("total") && !isTotalPresent(inv.total)) blockers.push("total");
  if (inScope("vendor") && !(inv.vendor ?? "").trim()) blockers.push("vendor");
  return blockers;
}

const BLOCKER_LABEL: Record<InvoiceBlockerKey, string> = {
  currency: "currency",
  total: "total",
  vendor: "vendor",
};

/** Human Issue line for missing financial/header fields. */
export function blockerIssueTitle(blockers: InvoiceBlockerKey[]): string | null {
  if (!blockers.length) return null;
  if (blockers.length === 1) {
    const only = blockers[0]!;
    if (only === "currency") return "Currency not extracted";
    if (only === "total") return "Total not extracted";
    return "Vendor not extracted";
  }
  const labels = blockers.map((key) => BLOCKER_LABEL[key]);
  return `Financial fields incomplete — ${labels.join(", ")}`;
}

/** Paired How to fix line for the same blockers. */
export function blockerFixHint(blockers: InvoiceBlockerKey[]): string | null {
  if (!blockers.length) return null;
  if (blockers.length === 1) {
    const only = blockers[0]!;
    if (only === "currency") {
      return "Fields tab — select currency, then save and continue";
    }
    if (only === "total") {
      return "Fields tab — enter total (and tax if needed), then continue";
    }
    return "Fields tab — enter vendor name, then save and continue";
  }
  return "Fields tab — complete currency, total, and line items, then Confirm & process";
}
