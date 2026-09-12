import { api } from "@/api/client";
import type {
  CollectionApi,
  Invoice,
  InvoiceDetails,
  InvoiceUpdatePayload,
  PaymentApi,
  ProcessingOverrides,
} from "@/api/types";
import { isPendingApprovalEvaluation } from "@/lib/invoice";
import {
  approvalChainProgressLabel,
  invoiceHasPendingQuorum,
} from "@/lib/approvalQuorum";
import {
  compulsoryFieldsForDocumentType,
  validateCompulsoryFieldsForApproval,
} from "@/lib/documentCompulsoryFields";
import { effectiveDocumentTypeCode } from "@/lib/documentTypeResolve";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export const APPROVAL_QUEUE_STATUSES = ["exception", "duplicate_skipped", "rejected"] as const;

export const PIPELINE_STATUSES = [
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
] as const;

const PROCESSING_POLL_MS = 2_000;
const PROCESSING_TIMEOUT_MS = 90_000;

const PIPELINE_ACTIVE = new Set<string>(PIPELINE_STATUSES);

function isVisionVaultTerminalInvoice(inv: Invoice): boolean {
  const evalStatus = (inv.evaluation_status ?? "").trim();
  if (evalStatus === "vision_vaulted") return true;
  const fields = inv.extracted_fields;
  const hasVisionBundle =
    fields != null &&
    typeof fields === "object" &&
    ("vision_bundle_kind" in fields || "vision_bundle_key" in fields);
  return evalStatus === "awaiting_classification" && hasVisionBundle;
}

export function canApproveClaim(status: string): boolean {
  return (APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
}

/** Approve from drawer — rejected/duplicate rows use Reprocess only. */
export function canApproveFromDrawer(invOrStatus: Invoice | string): boolean {
  const status = typeof invOrStatus === "string" ? invOrStatus : invOrStatus.status;
  if (!canApproveClaim(status) || status === "rejected" || status === "duplicate_skipped") {
    return false;
  }
  if (typeof invOrStatus !== "string" && isVisionVaultTerminalInvoice(invOrStatus)) {
    return false;
  }
  return true;
}

export function canRejectClaim(status: string): boolean {
  return status === "exception" || status === "processed";
}

/** Processed invoices can re-run the full pipeline; queue items use Approve. */
export function canQueuePipeline(status: string): boolean {
  return status === "processed";
}

/** Matches POST /api/invoices/{id}/reprocess allowed statuses. */
export function canReprocessInvoice(status: string): boolean {
  return (
    status === "exception" ||
    status === "duplicate_skipped" ||
    status === "processed" ||
    status === "rejected"
  );
}

/** Request approval / more info — not for posted docs or items already in the queue. */
export function canRequestInfo(status: string): boolean {
  if (status === "processed") return false;
  return !(APPROVAL_QUEUE_STATUSES as readonly string[]).includes(status);
}

/** Manager sign-off from the drawer — only when policy has already held the document. */
export function canManagerApproveFromDrawer(inv: Invoice): boolean {
  return canApproveFromDrawer(inv) && isPendingApprovalEvaluation(inv.evaluation_status);
}

export function validateInvoiceFieldsForApproval(
  fields: {
    vendor?: string | null;
    total?: string | null;
    due_date?: string | null;
    invoice_no?: string | null;
    po_reference?: string | null;
    invoice_date?: string | null;
    subtotal?: string | null;
    gst?: string | null;
    abn?: string | null;
    cost_centre?: string | null;
    billing_address?: string | null;
    line_items?: unknown[] | null;
  },
  compulsoryFields?: string[]
): { ok: true } | { ok: false; message: string } {
  if (!compulsoryFields?.length) {
    return { ok: true };
  }
  return validateCompulsoryFieldsForApproval(fields, compulsoryFields);
}

export function approvalFieldsFromInvoice(inv: {
  vendor?: string | null;
  total?: string | null;
  due_date?: string | null;
  invoice_no?: string | null;
  po_reference?: string | null;
  invoice_date?: string | null;
  subtotal?: string | null;
  gst?: string | null;
  abn?: string | null;
  cost_centre?: string | null;
  billing_address?: string | null;
  line_items?: unknown[] | null;
}) {
  return {
    vendor: inv.vendor ?? null,
    total: inv.total ?? null,
    due_date: inv.due_date ?? null,
    invoice_no: inv.invoice_no ?? null,
    po_reference: inv.po_reference ?? null,
    invoice_date: inv.invoice_date ?? null,
    subtotal: inv.subtotal ?? null,
    gst: inv.gst ?? null,
    abn: inv.abn ?? null,
    cost_centre: inv.cost_centre ?? null,
    billing_address: inv.billing_address ?? null,
    line_items: inv.line_items ?? null,
  };
}

/** @deprecated Use approvalFieldsFromInvoice */
export function invoiceFieldsFromDetails(inv: {
  vendor?: string | null;
  total?: string | null;
  due_date?: string | null;
}) {
  return approvalFieldsFromInvoice(inv);
}

export type ApprovalFieldBag = Parameters<typeof approvalFieldsFromInvoice>[0];

export function compulsoryFieldsForInvoice(
  inv: Pick<Invoice, "document_type_code" | "purchase_document_type" | "sales_document_type">,
  documentTypes: DocumentTypeDefinition[] | undefined
): string[] {
  if (!documentTypes?.length) return [];
  const code = effectiveDocumentTypeCode(inv, documentTypes);
  if (!code) return [];
  return compulsoryFieldsForDocumentType(documentTypes, code);
}

export const SETTLEMENT_FIELD_KEYS = ["vendor", "total", "due_date"] as const;

export type PostApprovalSettlement = "payment" | "collection" | "none";

type SettlementInvoiceShape = Pick<
  InvoiceDetails,
  | "route_target"
  | "vendor"
  | "total"
  | "due_date"
  | "sales_document_type"
  | "purchase_document_type"
  | "gl_posting_applicable"
>;

/** Route/doc shape that should produce payment or collection when amounts are present. */
export function expectedSettlementKind(inv: SettlementInvoiceShape): PostApprovalSettlement {
  const route = (inv.route_target ?? "").trim();
  if (route === "Vault" || route === "Team Expenses") return "none";
  if (inv.gl_posting_applicable === false) return "none";

  if (route === "Sales Management") {
    const salesDoc = (inv.sales_document_type ?? "").trim().toLowerCase();
    if (salesDoc === "so" || salesDoc === "dn") return "none";
    return "collection";
  }

  if (route === "Purchase Management" || route === "Expenses Management") {
    const purchaseDoc = (inv.purchase_document_type ?? "").trim().toLowerCase();
    if (purchaseDoc === "po" || purchaseDoc === "grn") return "none";
    return "payment";
  }

  return "none";
}

/** Fields still needed for settlement beyond what the document type already requires. */
export function settlementFieldsForApproval(inv: SettlementInvoiceShape): readonly string[] {
  return expectedSettlementKind(inv) === "none" ? [] : SETTLEMENT_FIELD_KEYS;
}

/** User-facing hint for settlement context after approve (informational only — not an approve gate). */
export function settlementApprovalHint(inv: SettlementInvoiceShape): string | null {
  const settlement = expectedSettlementKind(inv);
  if (settlement === "payment") {
    return "After approve, documents may enter the payments queue when vendor, total, and due date are present.";
  }
  if (settlement === "collection") {
    return "After approve, documents may enter the collections queue when customer, total, and due date are present.";
  }
  return null;
}

/** Client-side approve gate — document type compulsory fields saved in Rule Book. */
export function validateInvoiceReadyForApproval(
  inv: ApprovalFieldBag &
    Pick<
      Invoice,
      | "document_type_code"
      | "purchase_document_type"
      | "sales_document_type"
      | "route_target"
      | "gl_posting_applicable"
    >,
  documentTypes: DocumentTypeDefinition[] | undefined,
  fieldsOverride?: ApprovalFieldBag
): { ok: true } | { ok: false; message: string } {
  const fields = approvalFieldsFromInvoice(fieldsOverride ?? inv);
  if ((inv.route_target || "").trim() === "Team Expenses" ||
      (inv.route_target || "").trim() === "Expenses Management") {
    const raw = String(fields.total ?? "").trim();
    const n = Number(raw);
    if (!raw || Number.isNaN(n) || n <= 0) {
      return {
        ok: false,
        message:
          "Cannot approve: amount is missing or zero. Enter the amount on the Fields tab, save, then approve.",
      };
    }
  }
  const compulsory = compulsoryFieldsForInvoice(inv, documentTypes);
  return validateInvoiceFieldsForApproval(fields, compulsory.length ? compulsory : undefined);
}

export function approvalFailureMessage(inv: InvoiceDetails): string {
  if (inv.status === "exception") {
    if (inv.evaluation_status === "awaiting_po") {
      return "Approval blocked: a matching purchase order is required for this document.";
    }
    if (inv.evaluation_status === "pending_vendor") {
      return "Approval blocked: register the vendor in Vendors → Pending vendor registration, then approve again.";
    }
    if (inv.evaluation_status === "pending_approval") {
      return "Waiting for approver — use Approve when policy checks are satisfied.";
    }
    const hint = (inv.resolution_hint ?? "").trim();
    if (hint && !/open document( drawer)?/i.test(hint)) {
      return `Processing stopped: ${hint}`;
    }
    const issue = (inv.issue_summary ?? "").trim();
    if (/value too long|character varying/i.test(issue)) {
      return (
        "Processing stopped: a chart-of-accounts code is too long for posting. " +
        "Shorten the parent or sub-ledger code in Rule Book → Chart of accounts, then Approve again."
      );
    }
    const stage = (inv.current_stage ?? "").trim();
    if (inv.current_stage_state === "fail") {
      if (/posted|control account/i.test(stage)) {
        return "Processing stopped: a posting ledger is not selected in the chart of accounts. Open Rule Book → Posting → Team expense posting, pick the advance parent and settlement ledgers from COA, then Confirm & process again.";
      }
      if (stage) {
        return `Processing stopped at ${stage}. Check the Audit tab for the blocker.`;
      }
    }
    if (inv.evaluation_status === "needs_review") {
      return "Approval blocked: document still requires review after processing.";
    }
    const failed = inv.validation_results?.find((row) => !row.passed && !row.skipped);
    if (failed?.message) {
      return `Approval blocked: ${failed.message}`;
    }
    return "Approval did not complete — document returned to review. Check validation or routing rules.";
  }
  if (PIPELINE_ACTIVE.has(inv.status)) {
    return `Approval did not complete — processing still ${inv.status}. Wait or use Reprocess from the drawer.`;
  }
  return `Approval did not complete (status: ${inv.status}).`;
}

export async function watchProcessingUntilIdle(
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawRunning = false;
  while (Date.now() < deadline) {
    await refresh();
    const status = await api.getProcessingStatus();
    if (status.state === "running" || status.active_tasks > 0) {
      sawRunning = true;
    }
    if (sawRunning && status.state === "idle" && status.active_tasks === 0) {
      await refresh();
      return;
    }
    if (!sawRunning && status.state === "idle" && status.active_tasks === 0) {
      await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
      await refresh();
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

export type WatchInvoiceUntilSettledOptions = {
  /** Wait for a pipeline status before treating exception/rejected/processed as settled. */
  requirePipelineObserved?: boolean;
};

/** Poll one invoice until it leaves the pipeline (processed / exception / rejected). */
export async function watchInvoiceUntilSettled(
  invoiceId: number,
  refresh: () => Promise<void>,
  timeoutMs = PROCESSING_TIMEOUT_MS,
  options?: WatchInvoiceUntilSettledOptions
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawPipeline = !options?.requirePipelineObserved;
  // Poll invoice only — callers often pass a matrix reload as `refresh`;
  // hammering /api/matrix every tick is what floods the network tab after Approve.
  while (Date.now() < deadline) {
    const inv = await api.getInvoice(invoiceId, { fresh: true });
    if (PIPELINE_ACTIVE.has(inv.status)) {
      sawPipeline = true;
    }
    if (sawPipeline && !PIPELINE_ACTIVE.has(inv.status)) {
      await refresh();
      return;
    }
    await new Promise((r) => setTimeout(r, PROCESSING_POLL_MS));
  }
  await refresh();
}

/** True when a stored path exists or the API verified the blob (reprocess can repair paths). */
export function invoiceCanAttemptReprocess(inv: {
  has_stored_file?: boolean;
  raw_file_path?: string | null;
}): boolean {
  return Boolean(inv.has_stored_file || inv.raw_file_path?.trim());
}

function _truthyFlag(value: unknown): boolean {
  if (value === true) return true;
  if (typeof value === "string") {
    return ["1", "true", "yes"].includes(value.trim().toLowerCase());
  }
  return false;
}

/**
 * Without-document / manual-entry captures intentionally have no receipt blob.
 * Approve/confirm must not require a stored file for these rows.
 */
export function allowsApprovalWithoutStoredFile(inv: {
  extracted_fields?: object | null;
  processing_overrides?: ProcessingOverrides | object | null;
}): boolean {
  const fields = inv.extracted_fields as Record<string, unknown> | null | undefined;
  if (fields && typeof fields === "object") {
    if (_truthyFlag(fields.without_document) || _truthyFlag(fields.manual_entry)) {
      return true;
    }
  }
  const overrides = inv.processing_overrides as Record<string, unknown> | null | undefined;
  if (overrides && typeof overrides === "object" && _truthyFlag(overrides.skip_extraction)) {
    return true;
  }
  return false;
}

/** Approve/confirm may proceed when a file exists or the claim is without-document. */
export function invoiceHasApprovableSource(inv: {
  has_stored_file?: boolean;
  extracted_fields?: object | null;
  processing_overrides?: ProcessingOverrides | object | null;
}): boolean {
  return Boolean(inv.has_stored_file) || allowsApprovalWithoutStoredFile(inv);
}

/** Expected AR/AP side effect after a processed invoice, by route and field completeness. */
export function postApprovalSettlement(inv: SettlementInvoiceShape): PostApprovalSettlement {
  const kind = expectedSettlementKind(inv);
  if (kind === "none") return "none";

  const hasAmount =
    Boolean(inv.vendor?.trim()) &&
    Boolean(inv.total?.trim()) &&
    Number(inv.total) > 0;
  const hasDue = Boolean(inv.due_date?.trim());
  if (!hasAmount || !hasDue) return "none";

  return kind;
}

export type ApproveAndProcessResult = {
  invoice: InvoiceDetails;
  payment?: PaymentApi;
  collection?: CollectionApi;
  /** True when more distinct pool approvers are still required. */
  awaitingQuorum?: boolean;
  /** True when document-type / team-expense policy is holding for a manager. */
  awaitingApproval?: boolean;
  quorumLabel?: string | null;
};

async function settlementAfterProcessed(
  invoice: InvoiceDetails,
  invoiceId: number
): Promise<Pick<ApproveAndProcessResult, "payment" | "collection">> {
  const settlement = postApprovalSettlement(invoice);
  let payment: PaymentApi | undefined;
  let collection: CollectionApi | undefined;

  if (settlement === "payment") {
    const payments = await api.listPayments(undefined, { fresh: true });
    payment = payments.find((row) => row.invoice_id === invoiceId);
    if (!payment) {
      throw new Error(
        "Invoice processed but no payment row was created. If this is a supplier invoice, confirm vendor, total, and due date are present."
      );
    }
  } else if (settlement === "collection") {
    const collections = await api.listCollections({ fresh: true });
    collection = collections.find((row) => row.invoice_id === invoiceId);
    if (!collection) {
      throw new Error(
        "Invoice processed but no collection row was created. Confirm customer, total, and due date are present."
      );
    }
  }

  return { payment, collection };
}

export async function approveAndProcess(
  invoiceId: number,
  refresh: () => Promise<void>,
  pendingEdits?: InvoiceUpdatePayload
): Promise<ApproveAndProcessResult> {
  if (pendingEdits) {
    await api.updateInvoice(invoiceId, pendingEdits);
  }
  const approved = await api.approve(invoiceId);
  await refresh();

  if (invoiceHasPendingQuorum(approved)) {
    return {
      invoice: approved as InvoiceDetails,
      awaitingQuorum: true,
      quorumLabel: approvalChainProgressLabel(approved.approval_chain),
    };
  }

  // Approve sets mapping and resumes posting in the background. If the response
  // is already settled (resume finished during the request), skip the watch loop.
  if (!PIPELINE_ACTIVE.has(approved.status)) {
    const invoice = (await api.getInvoice(invoiceId, { fresh: true })) as InvoiceDetails;
    if (invoice.status === "processed") {
      const extra = await settlementAfterProcessed(invoice, invoiceId);
      return { invoice, ...extra };
    }
    throw new Error(approvalFailureMessage(invoice));
  }

  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS);
  const invoice = await api.getInvoice(invoiceId, { fresh: true });

  if (invoice.status !== "processed") {
    throw new Error(approvalFailureMessage(invoice));
  }

  const extra = await settlementAfterProcessed(invoice, invoiceId);
  return { invoice, ...extra };
}

/** Confirm saved fields and continue the pipeline without counting as manager approval. */
export async function confirmAndProcess(
  invoiceId: number,
  refresh: () => Promise<void>,
  pendingEdits?: InvoiceUpdatePayload
): Promise<ApproveAndProcessResult> {
  if (pendingEdits) {
    await api.updateInvoice(invoiceId, pendingEdits);
  }
  const queued = await api.confirmProcess(invoiceId);
  await refresh();

  const queuedSettled = !PIPELINE_ACTIVE.has(queued.status);
  if (queuedSettled) {
    const invoice = (await api.getInvoice(invoiceId, { fresh: true })) as InvoiceDetails;
    if (isPendingApprovalEvaluation(invoice.evaluation_status)) {
      return { invoice, awaitingApproval: true };
    }
    if (invoice.status === "processed") {
      const extra = await settlementAfterProcessed(invoice, invoiceId);
      return { invoice, ...extra };
    }
    throw new Error(approvalFailureMessage(invoice));
  }

  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS, {
    requirePipelineObserved: true,
  });

  const invoice = await api.getInvoice(invoiceId, { fresh: true });
  if (isPendingApprovalEvaluation(invoice.evaluation_status)) {
    return { invoice, awaitingApproval: true };
  }
  if (invoice.status !== "processed") {
    throw new Error(approvalFailureMessage(invoice));
  }

  const extra = await settlementAfterProcessed(invoice, invoiceId);
  return { invoice, ...extra };
}

/** Confirm document type and re-run the pipeline, polling until settled. */
export async function resolveClassificationAndWatch(
  invoiceId: number,
  confirmedDt: string,
  refresh: () => Promise<void>
): Promise<Invoice> {
  const queued = await api.resolveInvoiceClassification(invoiceId, {
    confirmed_dt: confirmedDt,
    reprocess: true,
  });
  if (!PIPELINE_ACTIVE.has(queued.status)) {
    await refresh();
    return queued;
  }
  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS, {
    requirePipelineObserved: true,
  });
  return api.getInvoice(invoiceId, { fresh: true });
}

/** Re-parse a stuck invoice (clears extracted fields, runs pipeline for this row). */
export async function reprocessAndWatch(
  invoiceId: number,
  refresh: () => Promise<void>,
  options?: { hadManualEdits?: boolean }
): Promise<void> {
  if (options?.hadManualEdits) {
    const proceed = window.confirm(
      "Reprocess re-runs OCR extraction and may still return to review. " +
        "To process with your saved corrections, use Approve instead. Continue reprocess?"
    );
    if (!proceed) return;
  }
  const queued = await api.reprocess(invoiceId);
  if (!PIPELINE_ACTIVE.has(queued.status)) {
    throw new Error(
      `Reprocess did not queue the pipeline (status: ${queued.status}). Check the stored file and try again.`
    );
  }
  await watchInvoiceUntilSettled(invoiceId, refresh, PROCESSING_TIMEOUT_MS, {
    requirePipelineObserved: true,
  });
}
