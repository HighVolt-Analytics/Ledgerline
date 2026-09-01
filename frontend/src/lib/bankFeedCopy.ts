/** Plain-language summaries of bank match_reasons for the review UI. */

import type { BankTransactionMatch } from "@/api/types";

export function formatMatchEntityLabel(
  match: Pick<
    BankTransactionMatch,
    "display_label" | "party_name" | "invoice_no" | "matched_type"
  >
): string {
  if (match.display_label?.trim()) return match.display_label.trim();
  const party = match.party_name?.trim();
  const invoice = match.invoice_no?.trim();
  if (party && invoice) return `${party} · ${invoice}`;
  if (party) return party;
  if (invoice) return invoice;
  return match.matched_type === "collection" ? "Collection" : "Payment";
}

export function formatMatchReasonsPlain(
  reasons: Record<string, unknown> | null | undefined
): string {
  if (!reasons || typeof reasons !== "object") return "";

  const parts: string[] = [];

  const amountScore = Number(reasons.amount_score);
  if (Number.isFinite(amountScore)) {
    if (amountScore >= 1) parts.push("Same amount");
    else if (amountScore >= 0.95) parts.push("Amount within 1 cent");
  }

  const dateDays = Number(reasons.date_days);
  if (Number.isFinite(dateDays) && Number(reasons.date_score) > 0) {
    if (dateDays === 0) parts.push("Same day");
    else if (dateDays === 1) parts.push("1 day apart");
    else parts.push(`${dateDays} days apart`);
  }

  const hit = reasons.reference_hit;
  if (typeof hit === "string" && hit.trim()) {
    const refScore = Number(reasons.reference_score);
    const label = hit.trim();
    if (Number.isFinite(refScore) && refScore >= 0.9) {
      parts.push(`matched invoice ${label}`);
    } else if (Number.isFinite(refScore) && refScore >= 0.6) {
      parts.push(`matched name ${label}`);
    } else {
      parts.push(`matched ${label}`);
    }
  }

  if (reasons.manual === true) {
    parts.push("Linked manually");
  }

  return parts.join(" · ");
}

export function formatMatchMethodLabel(method: string): string {
  if (method === "auto") return "Automatic";
  if (method === "suggested") return "Suggested";
  if (method === "manual") return "Manual";
  return "Linked";
}

export function formatBankAuditEvent(event: string): string {
  const map: Record<string, string> = {
    bank_txn_matched: "Matched",
    bank_txn_match_suggested: "Suggestion created",
    bank_txn_unmatched: "Unmatched",
    bank_txn_excluded: "Excluded",
    bank_txn_accepted: "Imported",
    bank_txn_categorized: "Categorized",
    bank_txn_category_overridden: "Category changed",
    bank_feed_import_started: "Import started",
    bank_feed_import_completed: "Import completed",
    bank_account_created: "Account created",
  };
  return map[event] ?? event.replace(/^bank_/, "").replace(/_/g, " ");
}

export function formatBankAuditDetail(
  detail: Record<string, unknown> | null
): string {
  if (!detail) return "";
  const parts: string[] = [];

  const method = detail.match_method;
  if (typeof method === "string") {
    parts.push(formatMatchMethodLabel(method));
  }

  const display =
    typeof detail.display_label === "string" ? detail.display_label.trim() : "";
  const party =
    typeof detail.party_name === "string" ? detail.party_name.trim() : "";
  const invoice =
    typeof detail.invoice_no === "string" ? detail.invoice_no.trim() : "";
  if (display) {
    parts.push(display);
  } else if (party || invoice) {
    parts.push([party, invoice].filter(Boolean).join(" · "));
  } else if (detail.matched_type != null) {
    parts.push(
      detail.matched_type === "payment"
        ? "Payment"
        : detail.matched_type === "collection"
          ? "Collection"
          : String(detail.matched_type)
    );
  }

  if (detail.allocated_amount != null) {
    parts.push(`linked ${String(detail.allocated_amount)}`);
  }

  if (detail.reason != null && String(detail.reason).trim()) {
    parts.push(String(detail.reason));
  }

  const category =
    typeof detail.category_coa === "string" ? detail.category_coa.trim() : "";
  if (category) parts.push(category);
  const ruleName =
    typeof detail.rule_name === "string" ? detail.rule_name.trim() : "";
  if (ruleName) parts.push(`rule ${ruleName}`);

  const nested = detail.match_reasons;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    const plain = formatMatchReasonsPlain(nested as Record<string, unknown>);
    if (plain) parts.push(plain);
  }

  return parts.join(" · ");
}

export type BankImportRowError = {
  rowNumber: number | null;
  message: string;
};

/** Extract per-row parse errors from a bank feed import error_report. */
export function parseBankImportErrorReport(
  report: Record<string, unknown> | unknown[] | null | undefined
): BankImportRowError[] {
  if (!report || Array.isArray(report) || typeof report !== "object") return [];
  const raw = report.parse_errors;
  if (!Array.isArray(raw)) return [];
  const out: BankImportRowError[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    const message = typeof row.message === "string" ? row.message.trim() : "";
    if (!message) continue;
    const rowNumber =
      typeof row.row_number === "number"
        ? row.row_number
        : Number.isFinite(Number(row.row_number))
          ? Number(row.row_number)
          : null;
    out.push({ rowNumber, message });
  }
  return out;
}

/** Import flash: always surface auto-categorize count when the API returns it. */
export function formatBankImportFlash(result: {
  accepted_count: number;
  row_count: number;
  duplicate_count: number;
  categorized_count?: number;
  extracted_count?: number;
  source?: string;
  reused_existing?: boolean;
  status?: string;
}): string {
  if (result.reused_existing) {
    return `Import already applied (${result.accepted_count} rows kept)`;
  }
  const categorized =
    typeof result.categorized_count === "number"
      ? ` · ${result.categorized_count} auto-categorized`
      : "";
  const dupes = result.duplicate_count
    ? ` · ${result.duplicate_count} duplicate(s) skipped`
    : "";
  const isPdf = (result.source || "").toLowerCase() === "pdf";
  const extracted =
    isPdf && typeof result.extracted_count === "number"
      ? `Extracted ${result.extracted_count} transaction(s) from statement · `
      : "";
  return `${extracted}Imported ${result.accepted_count} of ${result.row_count} rows${dupes}${categorized}`;
}
