import type { Invoice, InvoiceDetails } from "@/api/types";
import { reviewReasonLabel } from "@/lib/classificationAuditDisplay";
import { extractionFieldLabel } from "@/lib/documentExtractionFields";
import {
  effectiveValidationRules,
  type ValidationRuleConfig,
} from "@/lib/documentValidationChecks";

export const ROUTE_PURCHASE = "Purchase Management";
export const ROUTE_SALES = "Sales Management";
export const ROUTE_EXPENSES = "Expenses Management";
export const ROUTE_TEAM = "Team Expenses";
export const ROUTE_VAULT = "Vault";
export const ROUTE_UNROUTED = "Unrouted";

export type CounterpartyKind = "vendor" | "customer" | "employee" | "party";

/** Finance book role of the trading partner on a document (AP vendor vs AR customer). */
export function counterpartyKind(
  inv: Pick<Invoice, "route_target">,
): CounterpartyKind {
  const route = (inv.route_target ?? "").trim();
  if (route === ROUTE_SALES) return "customer";
  if (route === ROUTE_TEAM) return "employee";
  if (route === ROUTE_PURCHASE || route === ROUTE_EXPENSES) return "vendor";
  return "party";
}

export function counterpartyLabelForRoute(routeTarget: string | null | undefined): string {
  return counterpartyLabel({ route_target: routeTarget ?? null } as Invoice);
}

export function counterpartyLabel(inv: Pick<Invoice, "route_target">): string {
  const kind = counterpartyKind(inv);
  if (kind === "customer") return "Customer";
  if (kind === "employee") return "Employee";
  if (kind === "vendor") return "Vendor";
  return "Counterparty";
}

/** Table column when rows may span multiple finance books. */
export function counterpartyColumnLabel(options?: {
  routeTarget?: string | null;
  mixed?: boolean;
}): string {
  if (options?.mixed) return "Counterparty";
  if (options?.routeTarget?.trim()) return counterpartyLabelForRoute(options.routeTarget);
  return "Counterparty";
}

export function counterpartyMatchColumnLabel(options?: {
  routeTarget?: string | null;
  mixed?: boolean;
}): string {
  if (options?.mixed) return "Master match";
  const route = (options?.routeTarget ?? "").trim();
  if (route === ROUTE_SALES) return "Customer match";
  if (route === ROUTE_PURCHASE || route === ROUTE_EXPENSES) return "Vendor match";
  if (route === ROUTE_TEAM) return "Employee match";
  return "Master match";
}

/** Per-row inbox label — null when master match does not apply. */
export function counterpartyMatchLabel(
  inv: Pick<
    Invoice,
    "route_target" | "purchase_document_type" | "document_type_code" | "evaluation_status"
  >,
  documentTypes?: ValidationPassDocumentType[] | null,
): string | null {
  if (customerMatchApplicable(inv, documentTypes)) return "Customer match";
  if (vendorMatchApplicable(inv, documentTypes)) return "Vendor match";
  return null;
}

export function counterpartyName(
  inv: Pick<Invoice, "vendor" | "route_target" | "extracted_fields">,
): string {
  const fields = inv.extracted_fields ?? {};
  const kind = counterpartyKind(inv);
  const vendor = inv.vendor?.trim() || "";
  const buyer = fields.buyer_name?.trim() || "";
  const seller = fields.seller_name?.trim() || "";

  if (kind === "customer") {
    if (buyer) return buyer;
    if (vendor && vendor.toLowerCase() !== seller.toLowerCase()) return vendor;
    return vendor || buyer || "—";
  }
  if (kind === "vendor") {
    if (seller) return seller;
    return vendor || seller || "—";
  }
  return vendor || buyer || seller || "—";
}

export function counterpartyUnknownLabel(inv: Pick<Invoice, "route_target">): string {
  const kind = counterpartyKind(inv);
  if (kind === "customer") return "Unknown customer";
  if (kind === "employee") return "Unknown employee";
  if (kind === "vendor") return "Unknown vendor";
  return "Unknown counterparty";
}

export function extractionFieldLabelForInvoice(
  key: string,
  inv: Pick<Invoice, "route_target">,
  tax?: { label: string; rate: number | null },
): string {
  if (key === "gst" && tax) return `${tax.label} ${tax.rate ?? 0}%`;
  if (key === "vendor") return counterpartyLabel(inv);
  return extractionFieldLabel(key);
}

const VALIDATION_RULE_FIELDS: Record<string, readonly string[]> = {
  VR01: ["subtotal", "gst", "total"],
  VR02: ["invoice_no"],
  VR08: ["subtotal", "gst", "gst_rate", "total"],
  VR09: ["line_items"],
  VR11: ["invoice_date"],
  VR12: ["vendor"],
};

const OPTIONAL_EXTRACTION_FIELDS = new Set([
  "po_reference",
  "cost_centre",
  "bank_details",
  "attachment_name",
  "document_text",
]);

function vr03MissingFields(message: string): string[] {
  const marker = "Missing:";
  const idx = message.indexOf(marker);
  if (idx < 0) return [];
  return message
    .slice(idx + marker.length)
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function vr03AppliesToField(token: string, fieldKey: string): boolean {
  if (token === fieldKey) return true;
  if (fieldKey === "line_items" && token.startsWith("line_items")) return true;
  return false;
}

function headingFromDocumentText(text: string | null | undefined): string | null {
  if (!text) return null;
  for (const line of text.split(/\r?\n/)) {
    const token = line.trim();
    if (token.length >= 4) return token.slice(0, 120);
  }
  return null;
}

function extractionFieldPopulated(inv: InvoiceDetails, fieldKey: string): boolean {
  if (fieldKey === "line_items") return inv.line_items.length > 0;
  if (fieldKey === "bank_details") {
    return Boolean(inv.bank_bsb?.trim() || inv.bank_account?.trim());
  }
  if (fieldKey === "attachment_name") {
    return Boolean(inv.email_attachment_name?.trim());
  }
  if (fieldKey === "document_text") {
    return Boolean(inv.document_text?.trim());
  }
  if (fieldKey === "document_heading") {
    return Boolean(
      inv.document_heading?.trim() ||
        inv.extracted_fields?.document_heading?.trim() ||
        headingFromDocumentText(inv.document_text)
    );
  }
  const extracted = inv.extracted_fields?.[fieldKey];
  if (extracted != null && String(extracted).trim()) return true;
  const record = inv as unknown as Record<string, unknown>;
  const value = record[fieldKey];
  if (value == null) return false;
  return String(value).trim().length > 0;
}

function validationFailedForField(inv: Invoice, fieldKey: string): boolean {
  for (const result of invoiceFailedValidations(inv)) {
    if (result.rule === "VR03") {
      if (vr03MissingFields(result.message).some((token) => vr03AppliesToField(token, fieldKey))) {
        return true;
      }
      continue;
    }
    const fields = VALIDATION_RULE_FIELDS[result.rule];
    if (fields?.includes(fieldKey)) return true;
  }
  return false;
}

function fallbackFieldConfidence(inv: InvoiceDetails, fieldKey: string): number {
  if (fieldKey === "attachment_name" && inv.email_attachment_name?.trim()) {
    return 97;
  }

  const populated = extractionFieldPopulated(inv, fieldKey);
  const failed = validationFailedForField(inv, fieldKey);

  if (!populated) {
    if (OPTIONAL_EXTRACTION_FIELDS.has(fieldKey)) return 52;
    return failed ? 16 : 18;
  }

  if (failed) return 48;
  return 86;
}

/** Per-field extraction confidence for invoice drawers (from API when available). */
export function invoiceFieldConfidence(inv: InvoiceDetails, fieldKey: string): number {
  const fromApi = inv.extraction_field_confidence?.[fieldKey];
  if (fromApi != null && Number.isFinite(fromApi)) {
    return Math.round(fromApi);
  }
  return fallbackFieldConfidence(inv, fieldKey);
}

const VALIDATION_PASS_EXEMPT_ROUTES = new Set(["Vault", "Team Expenses"]);

export type ValidationPassDocumentType = {
  code: string;
  validation_profile?: string | null;
  validationProfile?: string | null;
  posting?: string | null;
  validationRules?: ValidationRuleConfig[];
  validation_rules?: ValidationRuleConfig[];
};

function vendorMasterCheckEnabled(definition: ValidationPassDocumentType): boolean {
  const rules = effectiveValidationRules({
    code: definition.code,
    validationProfile:
      definition.validationProfile ?? definition.validation_profile ?? undefined,
    validationRules: definition.validationRules ?? definition.validation_rules,
  });
  return rules.some((row) => row.code === "VR12" && row.enabled);
}

function postingPipelineAllowed(posting: string | null | undefined): boolean {
  const token = (posting ?? "").trim().toLowerCase();
  return token === "yes" || token === "conditional" || token === "down-payment";
}

/** Whether GL mapping/posting applies (mirrors backend gl_posting_applicable_for_invoice). */
export function glPostingApplicable(
  inv: Pick<
    Invoice,
    | "gl_posting_applicable"
    | "route_target"
    | "purchase_document_type"
    | "sales_document_type"
    | "document_type_code"
  >,
  documentTypes?: ValidationPassDocumentType[] | null,
): boolean {
  if (inv.gl_posting_applicable === false) return false;
  if (inv.gl_posting_applicable === true) return true;

  const purchaseDoc = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (purchaseDoc === "po" || purchaseDoc === "grn") return false;

  const salesDoc = (inv.sales_document_type ?? "").trim().toLowerCase();
  if (salesDoc === "so" || salesDoc === "dn") return false;

  const route = (inv.route_target ?? "").trim();
  if (VALIDATION_PASS_EXEMPT_ROUTES.has(route)) return false;

  const code = (inv.document_type_code ?? "").trim().toUpperCase();
  if (code && documentTypes?.length) {
    const definition = documentTypes.find((row) => row.code.toUpperCase() === code);
    if (definition && !postingPipelineAllowed(definition.posting)) return false;
  }

  return true;
}

/** Whether inbox VR pass % applies to this document (mirrors backend validation_pass_applicable). */
export function validationPassApplicable(
  inv: Pick<Invoice, "route_target" | "purchase_document_type" | "document_type_code">,
  documentTypes?: ValidationPassDocumentType[] | null,
): boolean {
  const purchaseDoc = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (purchaseDoc === "po" || purchaseDoc === "grn") return false;

  const route = (inv.route_target ?? "").trim();
  if (VALIDATION_PASS_EXEMPT_ROUTES.has(route)) return false;

  const code = (inv.document_type_code ?? "").trim().toUpperCase();
  if (code && documentTypes?.length) {
    const definition = documentTypes.find((row) => row.code.toUpperCase() === code);
    if (definition) {
      const profile = (
        definition.validation_profile ??
        definition.validationProfile ??
        ""
      )
        .trim()
        .toLowerCase();
      if (profile === "non_actionable") return false;
      if (!postingPipelineAllowed(definition.posting)) return false;
    }
  }

  return true;
}

/** Whether vendor master match % applies (mirrors backend vendor_registration_required). */
export function vendorMatchApplicable(
  inv: Pick<
    Invoice,
    "route_target" | "purchase_document_type" | "document_type_code" | "evaluation_status"
  >,
  documentTypes?: ValidationPassDocumentType[] | null,
): boolean {
  if (inv.evaluation_status === "pending_vendor") {
    const route = (inv.route_target ?? "").trim();
    return route === ROUTE_PURCHASE || route === ROUTE_EXPENSES;
  }

  const purchaseDoc = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (purchaseDoc === "po" || purchaseDoc === "grn") return false;

  const route = (inv.route_target ?? "").trim();
  if (VALIDATION_PASS_EXEMPT_ROUTES.has(route)) return false;
  if (route !== "Purchase Management" && route !== "Expenses Management") return false;

  const code = (inv.document_type_code ?? "").trim().toUpperCase();
    if (code && documentTypes?.length) {
    const definition = documentTypes.find((row) => row.code.toUpperCase() === code);
    if (definition) {
      if (!postingPipelineAllowed(definition.posting)) return false;
      return vendorMasterCheckEnabled(definition);
    }
  }

  return true;
}

/** Whether customer master match % applies (mirrors backend customer_registration_required). */
export function customerMatchApplicable(
  inv: Pick<
    Invoice,
    "route_target" | "document_type_code" | "evaluation_status"
  >,
  documentTypes?: ValidationPassDocumentType[] | null,
): boolean {
  if (inv.evaluation_status === "pending_vendor" && (inv.route_target ?? "").trim() === ROUTE_SALES) {
    return true;
  }

  const route = (inv.route_target ?? "").trim();
  if (route !== ROUTE_SALES) return false;

  const code = (inv.document_type_code ?? "").trim().toUpperCase();
  if (code && documentTypes?.length) {
    const definition = documentTypes.find((row) => row.code.toUpperCase() === code);
    if (definition) {
      if (!postingPipelineAllowed(definition.posting)) return false;
      return vendorMasterCheckEnabled(definition);
    }
  }

  return true;
}

/** Validation pass rate from API rules — null when not validated or not applicable. */
export function invoiceValidationConfidence(
  inv: Invoice,
  documentTypes?: ValidationPassDocumentType[] | null,
): number | null {
  if (inv.validation_pass_rate != null) {
    return inv.validation_pass_rate;
  }
  if (!validationPassApplicable(inv, documentTypes)) return null;
  const rules = inv.validation_results;
  if (!rules?.length) return null;
  const evaluated = rules.filter((r) => !r.skipped);
  if (evaluated.length === 0) return null;
  const passed = evaluated.filter((r) => r.passed).length;
  return Math.round((passed / evaluated.length) * 100);
}

/** Master match confidence for the finance counterparty — null when not scored. */
export function invoiceCounterpartyConfidence(
  inv: Invoice,
  documentTypes?: ValidationPassDocumentType[] | null,
): number | null {
  if (counterpartyKind(inv) === "customer") {
    return invoiceCustomerConfidence(inv, documentTypes);
  }
  return invoiceVendorConfidence(inv, documentTypes);
}

/** Customer match confidence when master registration applies — null when not scored. */
export function invoiceCustomerConfidence(
  inv: Invoice,
  documentTypes?: ValidationPassDocumentType[] | null,
): number | null {
  if (inv.evaluation_status === "pending_vendor") {
    return inv.vendor_confidence != null ? Math.round(inv.vendor_confidence) : 0;
  }
  if (!customerMatchApplicable(inv, documentTypes)) return null;
  if (inv.vendor_confidence != null) return Math.round(inv.vendor_confidence);
  if (inv.vendor?.trim() && inv.evaluation_status === "needs_review") {
    return 0;
  }
  return null;
}

/** Vendor match confidence when master registration applies — null when not scored. */
export function invoiceVendorConfidence(
  inv: Invoice,
  documentTypes?: ValidationPassDocumentType[] | null,
): number | null {
  if (inv.evaluation_status === "pending_vendor") {
    return inv.vendor_confidence != null ? Math.round(inv.vendor_confidence) : 0;
  }
  if (!vendorMatchApplicable(inv, documentTypes)) return null;
  if (inv.vendor_confidence != null) return Math.round(inv.vendor_confidence);
  if (
    inv.vendor?.trim() &&
    inv.evaluation_status &&
    (inv.evaluation_status === "unmatched_expense_vendor" ||
      inv.evaluation_status === "needs_review")
  ) {
    return 0;
  }
  return null;
}

export function isNeedsReviewEvaluation(status: string | null | undefined): boolean {
  return (status ?? "").trim() === "needs_review";
}

export function isPendingApprovalEvaluation(status: string | null | undefined): boolean {
  return (status ?? "").trim() === "pending_approval";
}

export function evaluationStatusLabel(
  status: Invoice["evaluation_status"],
  routeTarget?: string | null,
): string {
  if (status === "auto_coded") return "Auto coded";
  if (status === "needs_review") return "Needs review";
  if (status === "pending_approval") return "Pending approval";
  if (status === "awaiting_classification") return "Awaiting classification";
  if (status === "needs_rescan") return "Needs rescan";
  if (status === "pending_vendor") {
    return (routeTarget ?? "").trim() === ROUTE_SALES ? "Pending customer" : "Pending vendor";
  }
  if (status === "unmatched_expense_vendor") return "Unmatched vendor";
  if (status === "awaiting_po") return "Awaiting PO";
  if (status === "awaiting_so") return "Awaiting SO";
  return "—";
}

/** Short hint for inbox Evaluation column tooltips. */
export function evaluationStatusDescription(
  status: Invoice["evaluation_status"],
  routeTarget?: string | null,
): string {
  const isSales = (routeTarget ?? "").trim() === ROUTE_SALES;
  if (status === "auto_coded") {
    return "Route and coding rules matched — no manual routing step needed.";
  }
  if (status === "needs_review") {
    return "Document type, route, or GL mapping needs a human check before posting.";
  }
  if (status === "pending_approval") {
    return "Validation passed — waiting for approver sign-off per document-type policy.";
  }
  if (status === "awaiting_classification") {
    return "LLM confidence was below the auto-route threshold — confirm document type on the document.";
  }
  if (status === "needs_rescan") {
    return "Image or OCR quality was too poor — ask the sender for a flat, well-lit scan or PDF.";
  }
  if (status === "pending_vendor") {
    return isSales
      ? "Customer is not in master (VR12 on) — register in Creations → Customers before processing."
      : "Vendor is not in master (VR12 on) — register in Creations → Vendors before processing.";
  }
  if (status === "unmatched_expense_vendor") {
    return "Small expense from an unknown vendor — advisory only, not held. Raise expense_vendor_hold_above to block.";
  }
  if (status === "awaiting_po") {
    return "Purchase invoice is waiting for a PO link.";
  }
  if (status === "awaiting_so") {
    return "Sales invoice is waiting for SO or delivery note linkage.";
  }
  return "Not evaluated yet — still parsing or mapping.";
}

const STAGE_REVIEW_HINT: Record<string, string> = {
  Received: "Fields tab — check the captured document",
  Parsed: "Fields tab — confirm document type and extracted fields",
  Validated: "Audit tab — fix failed validation rules",
  Mapped: "Lines tab — review GL mapping on line items",
  Approved: "Waiting for approver sign-off",
};

function isSuspenseGlAccount(
  accountCode: string | null | undefined,
  accountName: string | null | undefined
): boolean {
  const token = `${accountName ?? ""} ${accountCode ?? ""}`.trim().toLowerCase();
  return /suspense|unmapped|unknown/.test(token);
}

function failedValidationHint(inv: Pick<Invoice, "validation_results">): string | null {
  const failed = invoiceFailedValidations(inv as Invoice);
  if (!failed.length) return null;
  const parts = failed
    .slice(0, 2)
    .map((row) => {
      const message = (row.message ?? "").trim();
      const rule = (row.rule ?? "").trim();
      if (rule && message) return `${rule} — ${message}`;
      return rule || message;
    })
    .filter(Boolean);
  if (!parts.length) return "Audit tab — fix failed validation rules";
  return `Audit tab — ${parts.join("; ")}`;
}

/** Actionable hover text — where to review, not just that review is needed. */
export function evaluationReviewTooltip(
  inv: Pick<
    Invoice,
    | "evaluation_status"
    | "validation_results"
    | "current_stage"
    | "current_stage_state"
    | "document_type_code"
    | "account_code"
    | "account_name"
    | "gl_posting_applicable"
    | "route_target"
    | "llm_suggested_dt"
    | "status"
  >,
  reviewReasons?: string[]
): string {
  const status = inv.evaluation_status;
  if (reviewReasons?.length) {
    return reviewReasons.map((code) => reviewReasonLabel(code)).join("; ");
  }

  const validationHint = failedValidationHint(inv);
  if (validationHint) return validationHint;

  if (status === "awaiting_classification") {
    const suggested = inv.llm_suggested_dt?.trim();
    return suggested
      ? `Fields tab — confirm document type (${suggested})`
      : "Fields tab — confirm document type";
  }

  if (status === "needs_review") {
    if (!inv.document_type_code?.trim()) {
      const suggested = inv.llm_suggested_dt?.trim();
      return suggested
        ? `Fields tab — confirm document type (${suggested})`
        : "Fields tab — confirm document type";
    }
    if (!inv.route_target?.trim()) {
      return "Fields tab — confirm routing (purchase, sales, or expense)";
    }
    if (
      inv.gl_posting_applicable !== false &&
      (!inv.account_code?.trim() || isSuspenseGlAccount(inv.account_code, inv.account_name))
    ) {
      return "Lines tab — assign a GL account or clear suspense mapping";
    }
    if (inv.current_stage_state === "fail") {
      const stage = inv.current_stage?.trim();
      if (stage && STAGE_REVIEW_HINT[stage]) return STAGE_REVIEW_HINT[stage]!;
      if (stage) return `Open document drawer — ${stage} step needs attention`;
    }
    if (inv.status === "exception") {
      return "Open document drawer — check Fields, Audit, or Lines tabs";
    }
    return "Open document drawer — check classification, validation, or GL mapping";
  }

  return evaluationStatusDescription(status, inv.route_target);
}

export function routeTargetShortLabel(route: string | null | undefined): string {
  if (!route) return "—";
  if (route === ROUTE_PURCHASE) return "Purchase";
  if (route === ROUTE_SALES) return "Sales";
  if (route === ROUTE_EXPENSES) return "Expenses";
  if (route === ROUTE_TEAM) return "Team";
  if (route === ROUTE_VAULT) return "Vault";
  return route;
}

export function invoiceFailedValidations(inv: Invoice) {
  return (inv.validation_results ?? []).filter((r) => !r.skipped && !r.passed);
}

/** Processed invoices with journal lines that can be posted to the workbook. */
export function invoiceCanPublishToLedger(inv: Invoice): boolean {
  if (inv.status !== "processed") return false;
  if (inv.published_to_ledger) return false;
  const route = (inv.route_target ?? "").trim().toLowerCase();
  if (route === "vault") return false;
  const docType = (inv.purchase_document_type ?? "").trim().toLowerCase();
  if (docType === "po" || docType === "grn") return false;
  return Boolean(inv.invoice_date);
}

export type InvoiceSource = "email" | "upload" | "onedrive" | "whatsapp" | "viber";

export function invoiceSourceKind(inv: Invoice): InvoiceSource {
  const capture = (inv.capture_source ?? "").trim().toLowerCase();
  if (capture === "whatsapp") return "whatsapp";
  if (capture === "viber") return "viber";
  if (capture === "email") return "email";

  const sender = (inv.email_sender ?? "").toLowerCase();
  if (sender.includes("onedrive") || sender.includes("sharepoint")) {
    return "onedrive";
  }
  if (inv.email_sender || inv.connected_mailbox_id) {
    return "email";
  }
  return "upload";
}

export function invoiceSourceLabel(source: InvoiceSource): string {
  if (source === "email") return "Email";
  if (source === "onedrive") return "OneDrive";
  if (source === "whatsapp") return "WhatsApp";
  if (source === "viber") return "Viber";
  return "Direct upload";
}

export type InvoiceDocType = "invoice" | "credit_note" | "po" | "grn";

export function invoiceDocumentType(inv: Invoice): InvoiceDocType {
  const purchaseType = inv.purchase_document_type?.toLowerCase();
  if (purchaseType === "po") return "po";
  if (purchaseType === "grn") return "grn";

  const ref = (inv.invoice_no ?? inv.po_reference ?? "").toLowerCase();
  if (
    ref.includes("credit") ||
    ref.includes("cn-") ||
    ref.startsWith("cn") ||
    ref.includes("credit-note")
  ) {
    return "credit_note";
  }
  for (const amount of [inv.total, inv.subtotal]) {
    if (amount == null || amount === "") continue;
    const n = parseFloat(String(amount));
    if (!Number.isNaN(n) && n < 0) return "credit_note";
  }
  return "invoice";
}

export function invoiceDocumentTypeLabel(type: InvoiceDocType): string {
  if (type === "credit_note") return "Credit Note";
  if (type === "po") return "Purchase Order";
  if (type === "grn") return "GRN";
  return "Invoice";
}

export function mailboxDisplayName(email: string, displayName: string | null): string {
  const label = displayName?.trim();
  if (label && !label.includes("@")) return label;
  const local = email.split("@")[0] ?? "Mailbox";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

export function invoiceMatchesMailbox(inv: Invoice, mailboxId: number): boolean {
  return inv.connected_mailbox_id === mailboxId;
}