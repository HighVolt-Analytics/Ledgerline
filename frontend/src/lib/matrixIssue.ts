import type { Invoice, ValidationResult } from "@/api/types";
import {
  blockerFixHint,
  blockerIssueTitle,
  detectInvoiceBlockers,
} from "@/lib/invoiceBlockers";
import { ROUTE_SALES } from "@/lib/invoice";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";

/** Pull the actionable phrase from a pipeline stage detail string. */
export function parseStageFailureDetail(detail: string | null | undefined): string {
  const raw = detail?.trim();
  if (!raw || raw === "—") return "Stage failed";
  const parts = raw
    .split("·")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1]!;
  return raw;
}

export type MatrixIssueSummary = {
  stage: MatrixStage | null;
  message: string;
};

const VAGUE_ISSUE_RE =
  /^(routed to (exception )?review|routed to exception review|failed checks|needs review|anomaly detected|exception review)$/i;

const GENERIC_RESOLUTION_HINT_RE =
  /open document( drawer)?\s*[—-]\s*check fields/i;

export function isVagueMatrixIssueMessage(message: string | null | undefined): boolean {
  const text = (message ?? "").trim();
  if (!text) return true;
  return VAGUE_ISSUE_RE.test(text) || /routed to (exception )?review/i.test(text);
}

function isGenericResolutionHint(hint: string | null | undefined): boolean {
  const text = (hint ?? "").trim();
  if (!text) return true;
  return isVagueMatrixIssueMessage(text) || GENERIC_RESOLUTION_HINT_RE.test(text);
}

function isSalesRoute(inv: Pick<Invoice, "route_target">): boolean {
  return (inv.route_target ?? "").trim() === ROUTE_SALES;
}

function isSuspenseGl(inv: Pick<Invoice, "account_code" | "account_name">): boolean {
  const token = `${inv.account_name ?? ""} ${inv.account_code ?? ""}`.trim().toLowerCase();
  return /suspense|unmapped|unknown/.test(token);
}

function firstFailedValidationMessage(inv: Invoice): string | null {
  const failed = failedValidationResults(inv);
  if (!failed.length) return null;
  const first = failed[0]!;
  const message = (first.message ?? "").trim();
  if (message) return message;
  const rule = (first.rule ?? "").trim();
  return rule ? `Validation rule ${rule} failed` : "Validation failed";
}

/**
 * Concrete Issue title when the pipeline only says "Routed to review".
 * Says what is wrong so the user can act without guessing.
 */
export function clarifyMatrixIssueTitle(inv: Invoice): string {
  const fromValidation = firstFailedValidationMessage(inv);
  if (fromValidation) return fromValidation;

  const status = (inv.evaluation_status ?? "").trim().toLowerCase();
  const suggested = inv.llm_suggested_dt?.trim();

  if (status === "awaiting_classification") {
    return suggested
      ? `Document type not classified (suggested ${suggested})`
      : "Document type not classified";
  }
  if (status === "vision_header_review") {
    const blockers = detectInvoiceBlockers(inv);
    const fromBlockers = blockerIssueTitle(blockers);
    return fromBlockers || "Header fields incomplete";
  }
  if (status === "pending_vendor") {
    return isSalesRoute(inv) ? "Customer not in master" : "Vendor not in master";
  }
  if (status === "unmatched_expense_vendor") {
    return "Unknown expense vendor";
  }
  if (status === "awaiting_po") {
    return "Awaiting PO linkage";
  }
  if (status === "awaiting_so") {
    return "Awaiting SO / DN linkage";
  }
  if (status === "pending_approval") {
    return "Needs approver sign-off";
  }
  if (status === "needs_rescan") {
    return "Poor scan quality — clearer PDF needed";
  }
  if (status === "line_gl_review") {
    return "Line GL mapping incomplete";
  }
  if (status === "line_items_review") {
    return "Line items incomplete or missing";
  }

  // Financial/header field gaps beat default Suspense GL fallback.
  const fieldBlockers = detectInvoiceBlockers(inv);
  const fieldTitle = blockerIssueTitle(fieldBlockers);
  if (fieldTitle) return fieldTitle;

  if (status === "needs_review" || !status) {
    if (!inv.document_type_code?.trim()) {
      return suggested
        ? `Document type not confirmed (suggested ${suggested})`
        : "Document type not confirmed";
    }
    if (!inv.route_target?.trim()) {
      return "Routing not confirmed (purchase / sales / expense)";
    }
    if (inv.gl_posting_applicable !== false && isSuspenseGl(inv)) {
      return "Suspense account — GL mapping unresolved";
    }
  }

  if (inv.gl_posting_applicable !== false && isSuspenseGl(inv) && !fieldBlockers.length) {
    return "Suspense account — GL mapping unresolved";
  }

  const apiHint = (inv.resolution_hint ?? "").trim();
  if (apiHint && !isGenericResolutionHint(apiHint)) {
    const parts = apiHint.split("—").map((p) => p.trim()).filter(Boolean);
    if (parts.length > 1 && /tab|board|register|creations/i.test(parts[0]!)) {
      return parts.slice(1).join(" — ");
    }
    return apiHint;
  }

  return "Needs manual review before approval / posting";
}

export function matrixIssueSummary(
  cells: Record<MatrixStage, MatrixCell>,
  flagReason?: string | null,
  inv?: Invoice | null
): MatrixIssueSummary | null {
  for (const stage of MATRIX_STAGES) {
    const cell = cells[stage];
    if (cell?.state === "fail") {
      let message = parseStageFailureDetail(cell.detail);
      if (inv && (isVagueMatrixIssueMessage(message) || isMisdiagnosedSuspense(message, inv))) {
        message = clarifyMatrixIssueTitle(inv);
      }
      return { stage, message };
    }
  }
  const trimmed = flagReason?.trim();
  if (trimmed) {
    let message = trimmed;
    if (inv && (isVagueMatrixIssueMessage(message) || isMisdiagnosedSuspense(message, inv))) {
      message = clarifyMatrixIssueTitle(inv);
    }
    return { stage: null, message };
  }
  return null;
}

/** Suspense GL label when Fields blockers are still open — rewrite to the real cause. */
function isMisdiagnosedSuspense(message: string, inv: Invoice): boolean {
  const text = message.toLowerCase();
  if (!text.includes("suspense") && !text.includes("unmapped gl") && !text.includes("gl mapping")) {
    return false;
  }
  return detectInvoiceBlockers(inv).length > 0;
}

const STAGE_FIX_HINT: Record<MatrixStage, string> = {
  Received: "Fields tab — check the captured document and reprocess if needed",
  Parsed: "Fields tab — confirm document type and extracted fields",
  Validated: "Audit tab — fix failed validation rules, then continue processing",
  Approved: "Approvals board — review and approve this document",
  Mapped: "Lines tab — assign or clear GL / suspense mapping on line items",
  Posted: "Audit tab — clear posting blockers, then reprocess or publish",
};

const FALLBACK_FIX = "Open document — check Fields, Audit, or Lines, fix the blocker, then continue";

function fixFromEvaluationStatus(inv: Invoice): string | null {
  const status = (inv.evaluation_status ?? "").trim().toLowerCase();
  if (!status) return null;

  if (status === "awaiting_classification") {
    const suggested = inv.llm_suggested_dt?.trim();
    return suggested
      ? `Fields tab — confirm document type (${suggested})`
      : "Fields tab — confirm document type";
  }
  if (status === "vision_header_review") {
    const blockers = detectInvoiceBlockers(inv);
    return blockerFixHint(blockers) || "Fields tab — complete header fields, save, then Confirm & process";
  }
  if (status === "pending_vendor") {
    return isSalesRoute(inv)
      ? "Creations → Customers — register customer, then reprocess"
      : "Creations → Vendors — register vendor, then reprocess";
  }
  if (status === "unmatched_expense_vendor") {
    return "Creations → Vendors — register vendor if needed, then reprocess";
  }
  if (status === "awaiting_po") {
    return "Purchase register — link or upload the PO, then reprocess";
  }
  if (status === "awaiting_so") {
    return "Sales register — link or upload the SO / DN, then reprocess";
  }
  if (status === "pending_approval") {
    return "Approvals board — review and approve this document";
  }
  if (status === "needs_rescan") {
    return "Ask sender for a clearer scan or PDF, then reprocess";
  }
  if (status === "line_gl_review") {
    return "Lines tab — pick a sub-ledger for each line under the document-type ledger";
  }
  if (status === "line_items_review") {
    return "Lines tab — add or correct required product lines, then continue processing";
  }
  // needs_review: do not return generic resolution_hint here — pair to blockers / message first
  return null;
}

function fixFromStructuralGaps(inv: Invoice): string | null {
  const blockers = detectInvoiceBlockers(inv);
  const fromBlockers = blockerFixHint(blockers);
  if (fromBlockers) return fromBlockers;

  if (!inv.document_type_code?.trim()) {
    const suggested = inv.llm_suggested_dt?.trim();
    return suggested
      ? `Fields tab — confirm document type (${suggested})`
      : "Fields tab — confirm document type";
  }
  if (!inv.route_target?.trim()) {
    return "Fields tab — confirm routing (purchase, sales, or expense)";
  }
  if (inv.gl_posting_applicable !== false && isSuspenseGl(inv)) {
    return "Lines tab — assign a GL account or clear suspense mapping";
  }
  return null;
}

function fixFromIssueMessage(message: string, inv: Invoice): string | null {
  const text = message.toLowerCase();
  if (!text) return null;

  if (text.includes("currency")) {
    return "Fields tab — select currency, then save and continue";
  }
  if (text.includes("total not extracted") || text.includes("financial fields incomplete")) {
    const blockers = detectInvoiceBlockers(inv);
    return blockerFixHint(blockers) || "Fields tab — enter total (and tax if needed), then continue";
  }
  if (text.includes("vendor not extracted")) {
    return "Fields tab — enter vendor name, then save and continue";
  }

  if (text.includes("not classified") || text.includes("confirm document type") || text.includes("document type not confirmed")) {
    const suggested = inv.llm_suggested_dt?.trim();
    return suggested
      ? `Fields tab — confirm document type (${suggested})`
      : "Fields tab — confirm document type";
  }
  if (text.includes("header") && (text.includes("review") || text.includes("incomplete"))) {
    const blockers = detectInvoiceBlockers(inv);
    return blockerFixHint(blockers) || "Fields tab — complete header fields, save, then Confirm & process";
  }
  if (
    text.includes("vendor could not be matched") ||
    text.includes("pending vendor") ||
    text.includes("vendor not in master") ||
    text.includes("unknown expense vendor")
  ) {
    return isSalesRoute(inv)
      ? "Creations → Customers — register customer, then reprocess"
      : "Creations → Vendors — register vendor, then reprocess";
  }
  if (text.includes("customer") && (text.includes("match") || text.includes("not in master"))) {
    return "Creations → Customers — register customer, then reprocess";
  }
  if (
    text.includes("suspense") ||
    text.includes("gl mapping unresolved") ||
    text.includes("control account") ||
    text.includes("line gl")
  ) {
    // If Fields blockers remain, prefer those over Lines/GL
    const blockers = detectInvoiceBlockers(inv);
    const fromBlockers = blockerFixHint(blockers);
    if (fromBlockers) return fromBlockers;
    return "Lines tab — assign a GL account or clear suspense mapping";
  }
  if (text.includes("duplicate")) {
    return "Open document — confirm it is unique to continue, or mark as duplicate";
  }
  if (text.includes("quarantined") || text.includes("rejected")) {
    return "Open document — Reprocess, or permanently delete";
  }
  if (text.includes("awaiting po") || (text.includes("po") && text.includes("link"))) {
    return "Purchase register — link or upload the PO, then reprocess";
  }
  if (text.includes("awaiting so") || text.includes("so / dn") || text.includes("delivery note")) {
    return "Sales register — link or upload the SO / DN, then reprocess";
  }
  if (
    text.includes("approver") ||
    text.includes("approval") ||
    text.includes("sign-off") ||
    text.includes("sign off")
  ) {
    return "Approvals board — review and approve this document";
  }
  if (text.includes("rescan") || text.includes("scan quality") || text.includes("poor image") || text.includes("clearer pdf")) {
    return "Ask sender for a clearer scan or PDF, then reprocess";
  }
  if (text.includes("routing not confirmed") || text.includes("rule book routing") || text.includes("routing needs")) {
    return "Fields tab — confirm routing (purchase, sales, or expense)";
  }
  if (text.includes("line items")) {
    return "Lines tab — add or correct required product lines, then continue processing";
  }
  if (isVagueMatrixIssueMessage(message)) {
    return fixFromStructuralGaps(inv) || FALLBACK_FIX;
  }
  if (text.includes("validation") || /^vr\d+/i.test(text.trim())) {
    return "Audit tab — fix failed validation rules, then continue processing";
  }
  if (text.includes("reconciliation")) {
    return "Audit tab — clear reconciliation blockers, then reprocess";
  }
  if (text.includes("manual review")) {
    return fixFromStructuralGaps(inv) || FALLBACK_FIX;
  }
  return null;
}

function fixFromFailedValidations(inv: Invoice): string | null {
  const failed = failedValidationResults(inv);
  if (!failed.length) return null;
  const first = failed[0]!;
  const rule = (first.rule ?? "").trim();
  const message = (first.message ?? "").trim();
  if (rule && message) {
    return `Audit tab — fix ${rule} (${message})`;
  }
  if (rule) return `Audit tab — fix failed validation rule ${rule}`;
  if (message) return `Audit tab — fix failed validation: ${message}`;
  return "Audit tab — fix failed validation rules, then continue processing";
}

/**
 * Hover text: how to fix — paired to the same issue shown in the Summary Issue column.
 * Never returns empty when an issue is present.
 */
export function matrixIssueFixHint(
  inv: Invoice,
  issue?: MatrixIssueSummary | null
): string {
  const status = (inv.status ?? "").trim().toLowerCase();

  // 1. Terminal invoice statuses
  if (status === "duplicate_skipped") {
    return "Open document — confirm it is unique to continue, or mark as duplicate";
  }
  if (status === "rejected") {
    return "Open document — Reprocess, or permanently delete";
  }

  // 2. Concrete displayed issue → pair How to fix first
  if (issue?.message && !isVagueMatrixIssueMessage(issue.message)) {
    const fromMessage = fixFromIssueMessage(issue.message, inv);
    if (fromMessage) return fromMessage;
  }

  // 3. Field blockers from invoice (currency / total / vendor)
  const blockers = detectInvoiceBlockers(inv);
  const fromBlockers = blockerFixHint(blockers);
  if (fromBlockers) return fromBlockers;

  // 4. Evaluation status (specific statuses only — not generic needs_review)
  const fromEval = fixFromEvaluationStatus(inv);
  if (fromEval) return fromEval;

  // 5. Structural gaps when the shown issue is vague
  if (issue && isVagueMatrixIssueMessage(issue.message)) {
    const structural = fixFromStructuralGaps(inv);
    if (structural) return structural;
  }

  // 6. Failed pipeline stage from the displayed issue
  if (issue?.stage && STAGE_FIX_HINT[issue.stage] && !isVagueMatrixIssueMessage(issue.message)) {
    const fromMessage = fixFromIssueMessage(issue.message, inv);
    if (fromMessage) return fromMessage;
    return STAGE_FIX_HINT[issue.stage];
  }
  if (issue?.stage && STAGE_FIX_HINT[issue.stage]) {
    const structural = fixFromStructuralGaps(inv);
    if (structural) return structural;
    const fromValidation = fixFromFailedValidations(inv);
    if (fromValidation) return fromValidation;
    return STAGE_FIX_HINT[issue.stage];
  }

  // 7. Issue / flag_reason text patterns (vague / remaining)
  const fromMessage = fixFromIssueMessage(issue?.message ?? "", inv);
  if (fromMessage) return fromMessage;

  // 8. Failed validation results
  const fromValidation = fixFromFailedValidations(inv);
  if (fromValidation) return fromValidation;

  // 9. API resolution_hint last (skip generic drawer fallback)
  const apiHint = (inv.resolution_hint ?? "").trim();
  if (apiHint && !isGenericResolutionHint(apiHint)) return apiHint;

  // 10. Last resort
  return fixFromStructuralGaps(inv) || FALLBACK_FIX;
}

export function failedValidationResults(inv: Invoice): ValidationResult[] {
  const rules = inv.validation_results ?? [];
  return rules.filter((rule) => !rule.skipped && !rule.passed);
}

export function matrixStageFailures(
  cells: Record<MatrixStage, MatrixCell>
): { stage: MatrixStage; message: string; detail: string }[] {
  return MATRIX_STAGES.flatMap((stage) => {
    const cell = cells[stage];
    if (cell?.state !== "fail") return [];
    return [
      {
        stage,
        message: parseStageFailureDetail(cell.detail),
        detail: cell.detail?.trim() || "—",
      },
    ];
  });
}
