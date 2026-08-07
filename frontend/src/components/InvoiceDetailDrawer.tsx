import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  Clock,
  FileText,
  Pencil,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import type {
  InvoiceDetails,
  InvoiceClassificationAudit,
  InvoiceUpdatePayload,
  LineItem,
  PipelineActivePath,
  PipelineAuditStep,
  PurchaseDossier,
  SalesDossierResponse,
} from "@/api/types";
import {
  InvoiceDocumentViewer,
  InvoicePreviewModeToggle,
  type PreviewPaneMode,
} from "@/components/InvoiceFilePreview";
import {
  DocumentSummaryPreview,
  formatMoney,
  invoiceTaxMeta,
} from "@/components/invoice-preview/DocumentSummaryPreview";
import { InvoiceClassificationPanel } from "@/components/invoices/InvoiceClassificationPanel";
import { DuplicateReviewBadge, EvaluationStatusBadge } from "@/components/inbox/EvaluationStatusBadge";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import { PipelineDebugPanel } from "@/components/invoices/PipelineDebugPanel";
import { DossierPipelineTimeline } from "@/components/dossiers/DossierPipelineTimeline";
import { PageTabs } from "@/components/PageTabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { documentDisplayRef, normalizeCurrencyCode, vendorInvoiceNo } from "@/lib/format";
import { CURRENCIES } from "@/lib/settingsData";
import { fetchDossierById, type DossierSummaryWithInvoiceId } from "@/lib/dossierApi";
import {
  additionalExtractedFieldKeys,
  lineItemGridTemplateColumns,
  resolvePreviewLineItems,
  countPreviewLineItems,
  isVisionHeaderPipelineSummary,
  type LineItemColumnVisibility,
  type PreviewLineItem,
} from "@/lib/invoicePreview";
import { cn } from "@/lib/cn";
import {
  approveAndProcess,
  canApproveFromDrawer,
  canRejectClaim,
  canRequestInfo,
  invoiceCanAttemptReprocess,
  reprocessAndWatch,
  settlementApprovalHint,
  validateInvoiceReadyForApproval,
} from "@/lib/invoiceActions";
import {
  counterpartyName,
  extractionFieldLabelForInvoice,
  glPostingApplicable,
  invoiceCanPublishToLedger,
  invoiceFieldConfidence,
} from "@/lib/invoice";
import { LineGlAccountCell } from "@/components/invoices/LineGlAccountCell";
import { effectiveMatchPolicy, isTwoWayMatchMode, matchTabLabel } from "@/lib/documentPlaybookConfig";
import { InvoiceProcessingOverridesSection } from "@/components/invoices/InvoiceProcessingOverridesSection";
import { InvoicePurchaseDossierSection } from "@/components/invoices/InvoicePurchaseDossierSection";
import { InvoiceSalesDossierSection } from "@/components/invoices/InvoiceSalesDossierSection";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useAuth } from "@/context/AuthContext";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import {
  extractionFieldsForDocumentType,
  isPresetExtractionFieldKey,
  normalizeExtractionFieldKeys,
} from "@/lib/documentExtractionFields";
import {
  processingOverridesPatchFromDraft,
  processingOverridesPayload,
  skipStepsFromInvoice,
  toggleStepRunning,
  type ProcessingOverrideStepId,
} from "@/lib/processingOverrides";

import {
  effectiveDocumentTypeCode,
  invoiceDocumentTypeDisplayLabel,
} from "@/lib/documentTypeResolve";
import { requiresClassificationConfirm } from "@/lib/classificationAuditDisplay";
import { shouldApplyDrawerInvoiceUpdate } from "@/lib/invoiceDrawerSync";
import {
  defaultAuditPathTab,
  filterPipelineStepsForPath,
} from "@/lib/pipelineAuditPaths";

const TABS = ["fields", "lines", "po", "tax", "audit", "overrides", "pipeline"] as const;
export type InvoiceDrawerTab = (typeof TABS)[number];
type Tab = InvoiceDrawerTab;

const TAB_LABELS: Record<Exclude<Tab, "po">, string> = {
  fields: "Fields",
  lines: "Line items",
  tax: "Tax",
  audit: "Processing",
  overrides: "Processing overrides",
  pipeline: "Pipeline (dev)",
};

function tabLabel(tab: Tab, routeTarget?: string | null, matchMode?: string | null): string {
  if (tab === "po") return matchTabLabel(routeTarget, matchMode);
  return TAB_LABELS[tab];
}

function canEdit(status: string): boolean {
  return ["exception", "duplicate_skipped", "rejected"].includes(status);
}

function extractionFieldDisplayLabel(
  key: string,
  inv: InvoiceDetails,
  tax: { label: string; rate: number | null }
): string {
  return extractionFieldLabelForInvoice(key, inv, tax);
}

function isEditableExtractionField(key: string, extractionFieldKeys: string[]): boolean {
  if (["line_items", "bank_details", "attachment_name", "document_text"].includes(key)) return false;
  if (isPresetExtractionFieldKey(key)) return true;
  return extractionFieldKeys.includes(key);
}

function customExtractionKeysForDraft(
  inv: InvoiceDetails,
  extractionFieldKeys: string[]
): string[] {
  const fromConfig = extractionFieldKeys.filter((key) => !isPresetExtractionFieldKey(key));
  if (fromConfig.length) return fromConfig;
  return Object.keys(inv.extracted_fields ?? {}).filter((key) => !isPresetExtractionFieldKey(key));
}

function invoiceScalarValue(inv: InvoiceDetails, key: string): string | null {
  const record = inv as unknown as Record<string, unknown>;
  const extracted = inv.extracted_fields;
  if (extracted && typeof extracted === "object") {
    const custom = extracted[key];
    if (custom != null && String(custom).trim()) {
      return String(custom).trim();
    }
  }
  const val = record[key];
  if (val == null) return null;
  const text = String(val).trim();
  return text || null;
}

function headingFromDocumentText(text: string | null | undefined): string | null {
  if (!text) return null;
  for (const line of text.split(/\r?\n/)) {
    const token = line.trim();
    if (token.length >= 4) return token.slice(0, 120);
  }
  return null;
}

function readExtractionFieldValue(
  key: string,
  inv: InvoiceDetails,
  draft: InvoiceEditDraft | null,
  editing: boolean,
  fmt: (value: string | null | undefined) => string,
  extractionFieldKeys: string[],
  absentFields: string[] = [],
  sourceKind: "email" | "upload" = "upload"
): string {
  if (key === "line_items") {
    const previewOpts = {
      absentFields,
      extractionFieldKeys,
      sourceKind,
      lineItems: editing && draft ? mapDraftLineItems(inv, draft) : undefined,
    };
    const count = countPreviewLineItems(inv, previewOpts);
    return count ? `${count} line item${count === 1 ? "" : "s"}` : "—";
  }
  if (key === "bank_details") {
    const parts = [inv.bank_bsb, inv.bank_account].filter(Boolean);
    return parts.length ? parts.join(" / ") : "—";
  }
  if (key === "attachment_name") {
    return inv.email_attachment_name?.trim() || "—";
  }
  if (key === "document_text") {
    const body = inv.document_text?.trim();
    if (!body) return "—";
    const max = 280;
    return body.length > max ? `${body.slice(0, max)}… (${body.length.toLocaleString()} chars)` : body;
  }
  if (key === "document_heading") {
    const direct = invoiceScalarValue(inv, key) ?? headingFromDocumentText(inv.document_text);
    return direct || "—";
  }
  if (editing && draft && isEditableExtractionField(key, extractionFieldKeys)) {
    if (isPresetExtractionFieldKey(key)) {
      const draftValue = draft[key as keyof InvoiceEditDraft];
      if (typeof draftValue === "string") {
        return draftValue;
      }
    } else if (key in draft.extractedFields) {
      return draft.extractedFields[key];
    }
  }
  if (key === "subtotal" || key === "gst" || key === "total") {
    if (editing && draft && isEditableExtractionField(key, extractionFieldKeys)) {
      return draft[key];
    }
    const raw = inv[key];
    return raw ? fmt(raw) : "—";
  }
  const raw = invoiceScalarValue(inv, key);
  if (raw) return raw;
  return "—";
}

function updateDraftExtractionField(
  draft: InvoiceEditDraft,
  key: string,
  value: string
): InvoiceEditDraft {
  switch (key) {
    case "vendor":
      return { ...draft, vendor: value };
    case "abn":
      return { ...draft, abn: value };
    case "invoice_no":
      return { ...draft, invoice_no: value };
    case "po_reference":
      return { ...draft, po_reference: value };
    case "cost_centre":
      return { ...draft, cost_centre: value };
    case "billing_address":
      return { ...draft, billing_address: value };
    case "invoice_date":
      return { ...draft, invoice_date: value };
    case "due_date":
      return { ...draft, due_date: value };
    case "subtotal":
      return { ...draft, subtotal: value };
    case "gst":
      return { ...draft, gst: value };
    case "total":
      return { ...draft, total: value };
    case "currency":
      return { ...draft, currency: value.trim().toUpperCase() };
    case "email_sender":
      return { ...draft, email_sender: value };
    default:
      if (!isPresetExtractionFieldKey(key)) {
        return {
          ...draft,
          extractedFields: { ...draft.extractedFields, [key]: value },
        };
      }
      return draft;
  }
}

function ConfidenceDot({ value }: { value: number | null }) {
  if (value == null || !Number.isFinite(value)) return null;
  const color =
    value >= 95
      ? "bg-[hsl(var(--chart-1))]"
      : value >= 80
        ? "bg-[hsl(43_74%_49%)]"
        : "bg-destructive";
  return (
    <span className="inline-flex items-center gap-1.5 tnum text-xs text-muted-foreground shrink-0">
      <span className={cn("h-2 w-2 rounded-full", color)} />
      {value}%
    </span>
  );
}

function strField(v: string | number | null | undefined): string {
  if (v == null) return "";
  return String(v);
}

type LineItemDraft = {
  id?: number;
  description: string;
  qty: string;
  unit_price: string;
  amount: string;
  sub_ledger: string;
};

type InvoiceEditDraft = {
  vendor: string;
  abn: string;
  invoice_no: string;
  po_reference: string;
  cost_centre: string;
  billing_address: string;
  invoice_date: string;
  due_date: string;
  subtotal: string;
  gst: string;
  total: string;
  currency: string;
  email_sender: string;
  line_items: LineItemDraft[];
  skip_steps: ProcessingOverrideStepId[];
  extractedFields: Record<string, string>;
};

const COMMON_CURRENCY_OPTIONS: { value: string; label: string }[] = [
  { value: "AUD", label: "AUD (A$)" },
  { value: "USD", label: "USD (US$)" },
  { value: "EUR", label: "EUR (€)" },
  { value: "GBP", label: "GBP (£)" },
  { value: "SGD", label: "SGD (S$)" },
  { value: "INR", label: "INR (₹)" },
  { value: "NZD", label: "NZD (NZ$)" },
  { value: "AED", label: "AED (د.إ)" },
  { value: "CAD", label: "CAD (C$)" },
  { value: "JPY", label: "JPY (¥)" },
  { value: "CHF", label: "CHF" },
  { value: "HKD", label: "HKD (HK$)" },
  { value: "MYR", label: "MYR (RM)" },
  { value: "THB", label: "THB (฿)" },
  { value: "PHP", label: "PHP (₱)" },
  { value: "CNY", label: "CNY (¥)" },
];

const INVOICE_CURRENCY_OPTIONS = Array.from(
  new Map(
    [
      ...COMMON_CURRENCY_OPTIONS,
      ...CURRENCIES.map((currency) => ({
        value: currency.code,
        label: `${currency.code} (${currency.symbol})`,
      })),
    ].map((option) => [option.value, option])
  ).values()
);

/** True ISO 4217 alpha-3 only — symbols like "$" do not count as set. */
function isSetInvoiceCurrency(currency: string | null | undefined): boolean {
  const code = normalizeCurrencyCode(currency);
  return Boolean(code && /^[A-Z]{3}$/.test(code));
}

function invoiceCurrencySymbol(inv: InvoiceDetails): string | null {
  if (isSetInvoiceCurrency(inv.currency)) return null;
  const symbol = (inv.extracted_fields?.currency_symbol ?? "").trim();
  return symbol || null;
}

function currencyNeedsSelection(inv: InvoiceDetails): boolean {
  return !isSetInvoiceCurrency(inv.currency);
}

function canSelectCurrency(inv: InvoiceDetails): boolean {
  return currencyNeedsSelection(inv) || canEdit(inv.status);
}

function draftFromInvoice(inv: InvoiceDetails, extractionFieldKeys: string[] = []): InvoiceEditDraft {
  const extractedFields: Record<string, string> = {};
  for (const key of customExtractionKeysForDraft(inv, extractionFieldKeys)) {
    extractedFields[key] = strField(inv.extracted_fields?.[key]);
  }
  return {
    vendor: strField(inv.vendor),
    abn: strField(inv.abn),
    invoice_no: strField(inv.invoice_no),
    po_reference: strField(inv.po_reference),
    cost_centre: strField(inv.cost_centre),
    billing_address: strField(inv.billing_address),
    invoice_date: strField(inv.invoice_date),
    due_date: strField(inv.due_date),
    subtotal: strField(inv.subtotal),
    gst: strField(inv.gst),
    total: strField(inv.total),
    currency: strField(inv.currency).toUpperCase(),
    email_sender: strField(inv.email_sender),
    line_items: inv.line_items.map((line) => ({
      id: line.id,
      description: strField(line.description),
      qty: strField(line.qty),
      unit_price: strField(line.unit_price),
      amount: strField(line.amount),
      sub_ledger: strField(line.sub_ledger),
    })),
    skip_steps: skipStepsFromInvoice(inv.processing_overrides),
    extractedFields,
  };
}

function emptyLineItem(): LineItemDraft {
  return { description: "", qty: "", unit_price: "", amount: "", sub_ledger: "" };
}

function mapDraftLineItems(inv: InvoiceDetails, draft: InvoiceEditDraft): LineItem[] {
  return draft.line_items.map((line, index) => ({
    id: line.id ?? -(index + 1),
    invoice_id: inv.id,
    description: line.description || null,
    qty: line.qty || null,
    unit_price: line.unit_price || null,
    amount: line.amount || null,
    tax_amount: null,
    sub_ledger: line.sub_ledger || null,
  }));
}

function LineItemsDrawerGrid({
  columns,
  withActions = false,
  editable = false,
  showGlAccount = false,
  inv,
  postingApplies = true,
  parentLedger = "",
  previewItems,
  draftItems,
  onDraftChange,
  emptyMessage,
}: {
  columns: LineItemColumnVisibility;
  withActions?: boolean;
  editable?: boolean;
  showGlAccount?: boolean;
  inv?: InvoiceDetails;
  postingApplies?: boolean;
  parentLedger?: string;
  previewItems?: PreviewLineItem[];
  draftItems?: LineItemDraft[];
  onDraftChange?: (items: LineItemDraft[]) => void;
  emptyMessage: string;
}) {
  const rowStyle = {
    gridTemplateColumns: lineItemGridTemplateColumns(columns, withActions, showGlAccount),
  };
  const { showQty, showUnitPrice, showAmount } = columns;
  const itemCount = editable ? (draftItems?.length ?? 0) : (previewItems?.length ?? 0);

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <div className="invoice-drawer-lines-edit text-sm">
        <div
          className="invoice-drawer-lines-edit-row invoice-drawer-lines-edit-row--head text-xs text-muted-foreground bg-muted/50"
          style={rowStyle}
        >
          <span className="px-3 py-2 font-medium">Description</span>
          {showQty && <span className="px-2 py-2 font-medium text-right">Qty</span>}
          {showUnitPrice && <span className="px-2 py-2 font-medium text-right">Unit</span>}
          {showAmount && <span className="px-2 py-2 font-medium text-right">Total</span>}
          {showGlAccount && <span className="px-3 py-2 font-medium">GL account</span>}
          {withActions && <span className="sr-only">Remove row</span>}
        </div>
        {itemCount === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground border-t border-border">
            {emptyMessage}
          </div>
        ) : editable && draftItems && onDraftChange ? (
          draftItems.map((line, index) => (
            <div
              key={line.id ?? `new-${index}`}
              className="invoice-drawer-lines-edit-row border-t border-border"
              style={rowStyle}
            >
              <div className="px-2 py-2">
                <Input
                  value={line.description}
                  onChange={(e) => {
                    const next = [...draftItems];
                    next[index] = { ...line, description: e.target.value };
                    onDraftChange(next);
                  }}
                  className="h-8 w-full min-w-0 text-sm block"
                />
              </div>
              {showQty && (
                <div className="px-2 py-2">
                  <Input
                    value={line.qty}
                    onChange={(e) => {
                      const next = [...draftItems];
                      next[index] = { ...line, qty: e.target.value };
                      onDraftChange(next);
                    }}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                    inputMode="decimal"
                  />
                </div>
              )}
              {showUnitPrice && (
                <div className="px-2 py-2">
                  <Input
                    value={line.unit_price}
                    onChange={(e) => {
                      const next = [...draftItems];
                      next[index] = { ...line, unit_price: e.target.value };
                      onDraftChange(next);
                    }}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                    inputMode="decimal"
                  />
                </div>
              )}
              {showAmount && (
                <div className="px-2 py-2">
                  <Input
                    value={line.amount}
                    onChange={(e) => {
                      const next = [...draftItems];
                      next[index] = { ...line, amount: e.target.value };
                      onDraftChange(next);
                    }}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                    inputMode="decimal"
                  />
                </div>
              )}
              {showGlAccount && postingApplies && parentLedger ? (
                <div className="px-3 py-2 align-top">
                  <LineGlAccountCell
                    line={{
                      id: line.id ?? -(index + 1),
                      invoice_id: inv?.id ?? 0,
                      description: line.description,
                      qty: line.qty,
                      unit_price: line.unit_price,
                      amount: line.amount,
                      tax_amount: null,
                      sub_ledger: line.sub_ledger || null,
                    }}
                    parentLedger={parentLedger}
                    postingApplies={postingApplies}
                    editable
                    onSubLedgerChange={(sub_ledger) => {
                      const next = [...draftItems];
                      next[index] = { ...line, sub_ledger };
                      onDraftChange(next);
                    }}
                  />
                </div>
              ) : null}
              {withActions && (
                <div className="px-1 py-2 flex justify-center">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                    aria-label="Remove line item"
                    onClick={() => onDraftChange(draftItems.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>
          ))
        ) : (
          previewItems?.map((line) => (
            <div
              key={line.id}
              className="invoice-drawer-lines-edit-row border-t border-border"
              style={rowStyle}
            >
              <div className="px-2 py-2">
                <Input
                  value={line.description ?? ""}
                  readOnly
                  tabIndex={-1}
                  className="h-8 w-full min-w-0 text-sm block"
                />
              </div>
              {showQty && (
                <div className="px-2 py-2">
                  <Input
                    value={line.displayQty ?? ""}
                    readOnly
                    tabIndex={-1}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                  />
                </div>
              )}
              {showUnitPrice && (
                <div className="px-2 py-2">
                  <Input
                    value={line.displayUnitPrice ?? ""}
                    readOnly
                    tabIndex={-1}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                  />
                </div>
              )}
              {showAmount && (
                <div className="px-2 py-2">
                  <Input
                    value={line.displayAmount ?? ""}
                    readOnly
                    tabIndex={-1}
                    className="h-8 w-full min-w-0 text-sm text-right tnum block"
                  />
                </div>
              )}
              {showGlAccount && inv && (
                <div className="px-3 py-2 align-top">
                  <LineGlAccountCell
                    line={line}
                    parentLedger={parentLedger || line.parent_ledger || inv.account_name || ""}
                    postingApplies={postingApplies}
                  />
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function payloadFromDraft(draft: InvoiceEditDraft, inv?: InvoiceDetails): InvoiceUpdatePayload {
  const payload: InvoiceUpdatePayload = {
    vendor: optionalText(draft.vendor),
    abn: optionalText(draft.abn),
    invoice_no: optionalText(draft.invoice_no),
    po_reference: optionalText(draft.po_reference),
    cost_centre: optionalText(draft.cost_centre),
    billing_address: optionalText(draft.billing_address),
    invoice_date: optionalText(draft.invoice_date),
    due_date: optionalText(draft.due_date),
    subtotal: optionalText(draft.subtotal),
    gst: optionalText(draft.gst),
    total: optionalText(draft.total),
    currency: optionalText(draft.currency)?.toUpperCase() ?? null,
    email_sender: optionalText(draft.email_sender),
    line_items: draft.line_items.map((line) => ({
      id: line.id,
      description: optionalText(line.description),
      qty: optionalText(line.qty),
      unit_price: optionalText(line.unit_price),
      amount: optionalText(line.amount),
      sub_ledger: optionalText(line.sub_ledger),
      gl_mapping_source: line.sub_ledger.trim() ? "manual" : undefined,
    })),
  };
  const overridesPatch = inv
    ? processingOverridesPatchFromDraft(draft.skip_steps, inv.processing_overrides)
    : processingOverridesPayload(draft.skip_steps);
  if (overridesPatch !== undefined) {
    payload.processing_overrides = overridesPatch;
  }
  const extracted_fields: Record<string, string> = {};
  for (const [key, value] of Object.entries(draft.extractedFields)) {
    const trimmed = value.trim();
    if (trimmed) extracted_fields[key] = trimmed;
  }
  if (Object.keys(extracted_fields).length) {
    payload.extracted_fields = extracted_fields;
  }
  return payload;
}

function FieldRow({
  label,
  value,
  confidence,
  bold,
  editable,
  onChange,
}: {
  label: string;
  value: string;
  confidence: number | null;
  bold?: boolean;
  editable?: boolean;
  onChange?: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 items-center">
      <label className="text-xs text-muted-foreground">{label}</label>
      <div className="flex items-center gap-2 min-w-0">
        <Input
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          className={cn("h-8 text-sm tnum", bold && "font-semibold")}
          readOnly={!editable}
        />
        {!editable && confidence != null && <ConfidenceDot value={confidence} />}
      </div>
    </div>
  );
}

function currencySelectOptions(current: string) {
  const selected = (current || "").trim().toUpperCase();
  if (
    !selected ||
    INVOICE_CURRENCY_OPTIONS.some((option) => option.value === selected)
  ) {
    return INVOICE_CURRENCY_OPTIONS;
  }
  // Rare valid ISO not in the curated list — still show the stored code so the
  // select is never blank while Total formats with that currency.
  return [
    ...INVOICE_CURRENCY_OPTIONS,
    { value: selected, label: `${selected} (from document)` },
  ];
}

function CurrencySelectRow({
  value,
  symbolHint,
  required,
  disabled,
  onChange,
}: {
  value: string;
  symbolHint?: string | null;
  required?: boolean;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const selected = (value || "").trim().toUpperCase();
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 items-center">
      <label className="text-xs text-muted-foreground">
        Currency{required ? " *" : ""}
      </label>
      <div className="min-w-0 space-y-1">
        <Select
          value={selected}
          disabled={disabled}
          onValueChange={onChange}
          options={currencySelectOptions(selected)}
          placeholder={
            symbolHint
              ? `Select ISO code (amounts show as ${symbolHint})`
              : "Select currency"
          }
          className={cn(
            "w-full",
            required && !selected && "border-destructive"
          )}
          data-testid="invoice-currency-select"
        />
        {required && !selected ? (
          <p className="text-[11px] text-destructive">
            Currency could not be extracted — select one for this invoice.
          </p>
        ) : symbolHint && !selected ? (
          <p className="text-[11px] text-muted-foreground">
            Detected symbol {symbolHint}; confirm the ISO currency code.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function pipelineDotClass(state: "done" | "pending" | "fail" | "skipped"): string {
  if (state === "done") return "bg-[hsl(var(--chart-1))]";
  if (state === "fail") return "bg-destructive";
  return "bg-muted-foreground/40";
}

type InvoiceDetailDrawerProps = {
  invoiceId: number | null;
  open: boolean;
  onClose: () => void;
  onUpdated?: () => void;
  onPipelineStart?: (invoice: InvoiceDetails) => void;
  onPipelineEnd?: (invoiceId: number) => void;
  onEditingChange?: (editing: boolean) => void;
  startInEditMode?: boolean;
  initialTab?: InvoiceDrawerTab;
};

export function InvoiceDetailDrawer({
  invoiceId,
  open,
  onClose,
  onUpdated,
  onPipelineStart,
  onPipelineEnd,
  onEditingChange,
  startInEditMode = false,
  initialTab = "fields",
}: InvoiceDetailDrawerProps) {
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const loadSeq = useRef(0);
  const [tab, setTab] = useState<Tab>(initialTab);
  const { data: ruleBook } = useRuleBookConfig(open);
  const [inv, setInv] = useState<InvoiceDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [sheetState, setSheetState] = useState<"open" | "closed">("closed");
  const [pipelineSteps, setPipelineSteps] = useState<PipelineAuditStep[]>([]);
  const [pipelineActivePath, setPipelineActivePath] = useState<PipelineActivePath>("unknown");
  const [auditPathTab, setAuditPathTab] = useState<"understood" | "not_understood">("understood");
  const [auditLoading, setAuditLoading] = useState(false);
  const [classificationAudit, setClassificationAudit] = useState<InvoiceClassificationAudit | null>(null);
  const [classificationLoading, setClassificationLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<InvoiceEditDraft | null>(null);
  const startInEditAppliedRef = useRef<number | null>(null);
  const [attachBusy, setAttachBusy] = useState(false);
  const [previewMode, setPreviewMode] = useState<PreviewPaneMode>("summary");
  const [viewId, setViewId] = useState<number | null>(null);
  const [dossier, setDossier] = useState<PurchaseDossier | null>(null);
  const [salesDossier, setSalesDossier] = useState<SalesDossierResponse | null>(null);
  const [dossierLoading, setDossierLoading] = useState(false);
  const [drawerDossier, setDrawerDossier] = useState<DossierSummaryWithInvoiceId | null>(null);
  const [drawerDossierLoading, setDrawerDossierLoading] = useState(false);
  /** Invoice id currently shown; async pipeline callbacks must not overwrite a newer selection. */
  const activeInvoiceIdRef = useRef<number | null>(null);
  const openRef = useRef(open);
  /** Pipeline op in flight for this id (approve/reprocess); busy UI only applies while still viewing it. */
  const pipelineBusyIdRef = useRef<number | null>(null);

  const activeInvoiceId = viewId ?? invoiceId;
  activeInvoiceIdRef.current = activeInvoiceId;
  openRef.current = open;

  const isStillViewing = useCallback((id: number | null | undefined) => {
    return shouldApplyDrawerInvoiceUpdate({
      open: openRef.current,
      activeInvoiceId: activeInvoiceIdRef.current,
      updatedId: id,
    });
  }, []);

  const catalogueCodes = useMemo(
    () =>
      (ruleBook?.documentTypes ?? [])
        .filter((dt) => dt.enabled)
        .map((dt) => dt.code),
    [ruleBook?.documentTypes]
  );

  const settlementHint = useMemo(
    () => (inv ? settlementApprovalHint(inv) : null),
    [inv]
  );

  const resolveClassification = async (confirmedDt: string) => {
    if (!activeInvoiceId) return;
    const targetId = activeInvoiceId;
    setActionBusy(true);
    try {
      await api.resolveInvoiceClassification(targetId, {
        confirmed_dt: confirmedDt,
        reprocess: true,
      });
      const [freshInv, freshAudit] = await Promise.all([
        api.getInvoice(targetId, { fresh: true }),
        api.getInvoiceClassificationAudit(targetId, { fresh: true }),
      ]);
      if (!isStillViewing(targetId)) return;
      setInv(freshInv);
      setClassificationAudit(freshAudit);
      onUpdated?.();
    } catch (err) {
      console.error(err);
    } finally {
      setActionBusy(false);
    }
  };

  useEffect(() => {
    if (open) {
      setTab(initialTab);
      setMounted(true);
      setSheetState("closed");
      const frame = requestAnimationFrame(() => {
        requestAnimationFrame(() => setSheetState("open"));
      });
      return () => cancelAnimationFrame(frame);
    }

    setSheetState("closed");
    const timer = window.setTimeout(() => setMounted(false), 300);
    return () => window.clearTimeout(timer);
  }, [open, invoiceId, initialTab]);

  useEffect(() => {
    setPreviewMode("summary");
  }, [invoiceId, open]);

  useEffect(() => {
    setViewId(null);
  }, [invoiceId, open]);

  useLayoutEffect(() => {
    loadSeq.current += 1;
    setInv(null);
    setPipelineSteps([]);
    setClassificationAudit(null);
    setDossier(null);
    setSalesDossier(null);
  }, [activeInvoiceId, tenantScope]);

  useEffect(() => {
    if (!mounted || activeInvoiceId == null) {
      if (!mounted) {
        setInv(null);
        setPipelineSteps([]);
        setClassificationAudit(null);
        setPreviewMode("summary");
        setDossier(null);
      }
      return;
    }
    if (!canRenderTenantOwnedUi(tenantScope)) return;

    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    setLoading(true);
    api
      .getInvoice(activeInvoiceId, { fresh: true })
      .then((data) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setInv(data);
      })
      .catch(() => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setInv(null);
      })
      .finally(() => {
        if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope)) setLoading(false);
      });
  }, [mounted, activeInvoiceId, tenantScope]);

  useEffect(() => {
    if (!inv) {
      setClassificationAudit(null);
      return;
    }
    const targetId = inv.id;
    setClassificationLoading(true);
    api
      .getInvoiceClassificationAudit(targetId, { fresh: true })
      .then((detail) => {
        if (activeInvoiceIdRef.current !== targetId) return;
        const hasAudit =
          detail &&
          (detail.document_type_code ||
            detail.llm_suggested_dt ||
            (Array.isArray(detail.review_reasons) && detail.review_reasons.length > 0));
        setClassificationAudit(hasAudit ? detail : null);
      })
      .catch(() => {
        if (activeInvoiceIdRef.current !== targetId) return;
        setClassificationAudit(null);
      })
      .finally(() => {
        if (activeInvoiceIdRef.current === targetId) setClassificationLoading(false);
      });
  }, [inv?.id]);

  useEffect(() => {
    if (!inv || tab !== "po") return;
    setDossierLoading(true);
    const isSales = (inv.route_target ?? "").toLowerCase().includes("sales");
    const request = isSales
      ? api.fetchSalesDossier(inv.id, { fresh: true }).then(setSalesDossier)
      : api.getPurchaseDossier(inv.id, { fresh: true }).then(setDossier);
    void request
      .catch(() => {
        if (isSales) setSalesDossier(null);
        else setDossier(null);
      })
      .finally(() => setDossierLoading(false));
  }, [inv, tab]);

  useEffect(() => {
    if (!open || tab !== "pipeline" || !invoiceId) {
      setDrawerDossier(null);
      return;
    }
    const dossierKey = documentDisplayRef({ id: invoiceId });
    setDrawerDossierLoading(true);
    void fetchDossierById(dossierKey)
      .then((row) => setDrawerDossier(row))
      .catch(() => setDrawerDossier(null))
      .finally(() => setDrawerDossierLoading(false));
  }, [open, tab, invoiceId]);

  const reloadDossier = useCallback(() => {
    if (!inv) return;
    setDossierLoading(true);
    const isSales = (inv.route_target ?? "").toLowerCase().includes("sales");
    const request = isSales
      ? api.fetchSalesDossier(inv.id, { fresh: true }).then(setSalesDossier)
      : api.getPurchaseDossier(inv.id, { fresh: true }).then(setDossier);
    void request
      .catch(() => {
        if (isSales) setSalesDossier(null);
        else setDossier(null);
      })
      .finally(() => setDossierLoading(false));
  }, [inv]);

  useEffect(() => {
    if (!inv || tab !== "audit") return;
    setAuditLoading(true);
    api
      .getInvoicePipeline(inv.id, { fresh: true })
      .then((res) => {
        setPipelineSteps(res.steps);
        setPipelineActivePath(res.active_path);
        setAuditPathTab(defaultAuditPathTab(res.active_path));
      })
      .catch(() => {
        setPipelineSteps([]);
        setPipelineActivePath("unknown");
        setAuditPathTab("understood");
      })
      .finally(() => setAuditLoading(false));
  }, [inv, tab]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
      setDraft(null);
      startInEditAppliedRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    setEditing(false);
    setDraft(null);
    startInEditAppliedRef.current = null;
    // A pipeline/save started on another invoice must not leave this one stuck busy.
    setActionBusy(false);
    setAttachBusy(false);
  }, [activeInvoiceId]);

  useEffect(() => {
    onEditingChange?.(editing);
  }, [editing, onEditingChange]);

  useEffect(() => {
    if (!open || !inv) return;
    if (
      startInEditMode &&
      canEdit(inv.status) &&
      startInEditAppliedRef.current !== inv.id
    ) {
      startInEditAppliedRef.current = inv.id;
      setEditing(true);
      setDraft(draftFromInvoice(inv));
      setTab("fields");
    }
  }, [inv?.id, startInEditMode, open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  const resolvedDocumentTypeCode = useMemo(() => {
    if (!inv || !ruleBook) return "";
    return effectiveDocumentTypeCode(inv, ruleBook.documentTypes);
  }, [inv, ruleBook]);

  const classificationConfirmRequired = useMemo(
    () => requiresClassificationConfirm(inv),
    [inv]
  );

  const extractionFieldKeys = useMemo(() => {
    if (!inv) return [];
    const fromApi = normalizeExtractionFieldKeys(inv.document_type_extraction_fields ?? undefined);
    let keys =
      fromApi.length > 0
        ? fromApi
        : ruleBook && resolvedDocumentTypeCode
          ? extractionFieldsForDocumentType(ruleBook.documentTypes, resolvedDocumentTypeCode)
          : [];
    // Team Expenses identity comes from the capture channel sender; keep it visible for review.
    if (
      (inv.route_target || "").trim() === "Team Expenses" &&
      !keys.includes("email_sender")
    ) {
      keys = ["email_sender", ...keys];
    }
    return keys;
  }, [inv, ruleBook, resolvedDocumentTypeCode]);

  const extraExtractedFieldKeys = useMemo(() => {
    if (!inv) return [];
    return additionalExtractedFieldKeys(inv, extractionFieldKeys);
  }, [inv, extractionFieldKeys]);

  const documentTypeInCatalogue = useMemo(() => {
    const code = resolvedDocumentTypeCode;
    if (!code || !ruleBook) return false;
    return ruleBook.documentTypes.some((dt) => dt.code.toUpperCase() === code);
  }, [resolvedDocumentTypeCode, ruleBook]);

  const documentTypeBadgeLabel = useMemo(() => {
    if (!inv) return null;
    if (!ruleBook) {
      return invoiceDocumentTypeDisplayLabel(inv, null);
    }
    return invoiceDocumentTypeDisplayLabel(inv, ruleBook.documentTypes);
  }, [inv, ruleBook]);

  const resolvedDocType = useMemo(() => {
    const code = resolvedDocumentTypeCode;
    if (!code || !ruleBook) return null;
    return (
      ruleBook.documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase()) ?? null
    );
  }, [resolvedDocumentTypeCode, ruleBook]);

  const invoiceMatchMode = useMemo(() => {
    if (resolvedDocType) return effectiveMatchPolicy(resolvedDocType).mode;
    return null;
  }, [resolvedDocType]);

  const absentFields = resolvedDocType?.absentFields ?? [];

  const postingApplies = useMemo(
    () => (inv ? glPostingApplicable(inv, ruleBook?.documentTypes) : true),
    [inv, ruleBook?.documentTypes]
  );

  const parentLedger = useMemo(() => {
    const fromDocType = resolvedDocType?.postTo?.ledger?.trim();
    if (fromDocType) return fromDocType;
    return inv?.account_name?.trim() ?? "";
  }, [resolvedDocType?.postTo?.ledger, inv?.account_name]);

  const previewLineItems = useMemo((): LineItem[] | undefined => {
    if (!inv || !editing || !draft) return undefined;
    return mapDraftLineItems(inv, draft);
  }, [inv, editing, draft]);

  const drawerLineItems = useMemo(() => {
    if (!inv) {
      return {
        previewItems: [] as PreviewLineItem[],
        columns: { showQty: false, showUnitPrice: false, showAmount: false },
      };
    }
    if (editing && draft) {
      const draftRows = mapDraftLineItems(inv, draft);
      const resolved = resolvePreviewLineItems(inv, {
        absentFields,
        extractionFieldKeys,
        sourceKind: inv.email_sender ? "email" : "upload",
        lineItems: draftRows,
      });
      return {
        previewItems: resolved.items,
        columns: resolved.columns,
      };
    }
    const resolved = resolvePreviewLineItems(inv, {
      absentFields,
      extractionFieldKeys,
      sourceKind: inv.email_sender ? "email" : "upload",
    });
    return { previewItems: resolved.items, columns: resolved.columns };
  }, [inv, editing, draft, absentFields, extractionFieldKeys]);

  const filteredAuditSteps = useMemo(
    () => filterPipelineStepsForPath(pipelineSteps, auditPathTab),
    [pipelineSteps, auditPathTab]
  );

  if (!mounted) return null;

  const tax = inv ? invoiceTaxMeta(inv) : { label: "Tax", rate: null };
  const currencySymbolHint = inv ? invoiceCurrencySymbol(inv) : null;
  const fmt = (v: string | null | undefined) =>
    inv ? formatMoney(v, inv.currency, undefined, currencySymbolHint) : "—";
  const sourceKind = inv?.email_sender ? "email" : "upload";
  const docNumber = inv ? (vendorInvoiceNo(inv) ?? documentDisplayRef(inv)) : "—";

  async function reloadInvoice(expectedId?: number) {
    const id = expectedId ?? activeInvoiceIdRef.current;
    if (id == null) return;
    const updated = await api.getInvoice(id, { fresh: true });
    if (!isStillViewing(id)) return;
    setInv(updated);
    if (tab === "audit") {
      const res = await api.getInvoicePipeline(id, { fresh: true });
      if (!isStillViewing(id)) return;
      setPipelineSteps(res.steps);
      setPipelineActivePath(res.active_path);
      setAuditPathTab(defaultAuditPathTab(res.active_path));
    }
  }

  async function handleSaveEdits() {
    if (!inv || !draft) return;
    const targetId = inv.id;
    setActionBusy(true);
    try {
      const updated = await api.updateInvoice(targetId, payloadFromDraft(draft, inv));
      if (!isStillViewing(targetId)) return;
      setInv(updated);
      setEditing(false);
      setDraft(null);
      onUpdated?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Save failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleCurrencySelect(code: string) {
    if (!inv || !canSelectCurrency(inv)) return;
    const targetId = inv.id;
    const next = code.trim().toUpperCase();
    if (!next || !/^[A-Z]{3}$/.test(next)) return;
    if (editing && draft) {
      setDraft({ ...draft, currency: next });
    }
    setActionBusy(true);
    try {
      const updated = await api.updateInvoice(targetId, { currency: next });
      if (!isStillViewing(targetId)) return;
      setInv(updated);
      if (editing) {
        setDraft(draftFromInvoice(updated, extractionFieldKeys));
      }
      onUpdated?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Currency update failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleAttachPdf(file: File) {
    if (!inv) return;
    const targetId = inv.id;
    setAttachBusy(true);
    try {
      await api.attachInvoiceFile(targetId, file);
      const updated = await api.getInvoice(targetId, { fresh: true });
      if (!isStillViewing(targetId)) return;
      setInv(updated);
      if (editing && draft) {
        setDraft(draftFromInvoice(updated, extractionFieldKeys));
      }
      onUpdated?.();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Attach failed");
    } finally {
      setAttachBusy(false);
    }
  }

  function startEditing() {
    if (!inv || !canEdit(inv.status)) return;
    setEditing(true);
    setDraft(draftFromInvoice(inv, extractionFieldKeys));
    if (tab !== "overrides") {
      setTab("fields");
    }
  }

  function ensureLineItemsEditMode() {
    if (!inv || !canEdit(inv.status)) return;
    setEditing(true);
    setDraft((current) => current ?? draftFromInvoice(inv, extractionFieldKeys));
  }

  function selectTab(next: Tab) {
    setTab(next);
  }

  function openLineItemsForEdit() {
    ensureLineItemsEditMode();
    setTab("lines");
  }

  function cancelEditing() {
    setEditing(false);
    setDraft(null);
  }

  function approvalFieldsFromDraftOrInvoice() {
    const source = editing && draft ? draft : inv;
    if (!source) {
      return { vendor: null, total: null, due_date: null };
    }
    return {
      vendor: source.vendor ?? null,
      total: source.total ?? null,
      due_date: source.due_date ?? null,
      invoice_no: source.invoice_no ?? null,
      po_reference: source.po_reference ?? null,
      invoice_date: source.invoice_date ?? null,
      subtotal: source.subtotal ?? null,
      gst: source.gst ?? null,
      abn: source.abn ?? null,
      cost_centre: source.cost_centre ?? null,
      billing_address: source.billing_address ?? null,
      line_items: "line_items" in source ? source.line_items ?? null : null,
    };
  }

  async function handleReject() {
    if (!inv || !canRejectClaim(inv.status)) return;
    if (!window.confirm(`Reject ${inv.vendor ?? documentDisplayRef(inv)}?`)) return;
    const targetId = inv.id;
    setActionBusy(true);
    try {
      await api.reject(targetId);
      onUpdated?.();
      if (isStillViewing(targetId)) onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        alert("Your role does not have permission to reject documents.");
      } else {
        alert(e instanceof Error ? e.message : "Reject failed");
      }
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRequestApproval() {
    if (!inv || !canRequestInfo(inv.status)) return;
    const targetId = inv.id;
    setActionBusy(true);
    try {
      await api.requestApproval(targetId);
      onUpdated?.();
      if (isStillViewing(targetId)) onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Request failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleReprocess() {
    if (!inv || inv.status !== "rejected") {
      if (inv?.status === "duplicate_skipped") {
        alert(
          "This row is a duplicate submission with no stored file. Delete it permanently or open the original invoice to reprocess."
        );
      }
      return;
    }
    if (!invoiceCanAttemptReprocess(inv)) {
      alert("Upload a PDF before reprocessing this invoice.");
      return;
    }
    const targetId = inv.id;
    pipelineBusyIdRef.current = targetId;
    setActionBusy(true);
    onPipelineStart?.(inv);
    try {
      if (editing && draft) {
        await api.updateInvoice(targetId, payloadFromDraft(draft, inv));
        if (isStillViewing(targetId)) {
          setEditing(false);
          setDraft(null);
        }
      }
      await reprocessAndWatch(targetId, async () => {
        onUpdated?.();
        await reloadInvoice(targetId);
      });
      onUpdated?.();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Reprocess failed");
    } finally {
      if (pipelineBusyIdRef.current === targetId) pipelineBusyIdRef.current = null;
      onPipelineEnd?.(targetId);
      setActionBusy(false);
    }
  }

  async function handleApproveAndProcess() {
    if (!inv) return;
    const targetId = inv.id;
    const fresh = await api.getInvoice(targetId, { fresh: true });
    if (!isStillViewing(targetId)) return;
    setInv(fresh);
    if (!canApproveFromDrawer(fresh)) {
      alert(
        fresh.status === "processed"
          ? "This invoice is already processed. Use Reprocess to run the pipeline again."
          : fresh.status === "rejected" || fresh.status === "duplicate_skipped"
            ? "Rejected documents must be reprocessed from the Rejected column."
            : "This invoice is not in the approval queue."
      );
      return;
    }
    if (!fresh.has_stored_file) {
      alert("Upload a PDF before approving this invoice.");
      return;
    }

    const fieldCheck = validateInvoiceReadyForApproval(
      inv,
      ruleBook?.documentTypes,
      approvalFieldsFromDraftOrInvoice()
    );
    if (!fieldCheck.ok) {
      alert(fieldCheck.message);
      return;
    }

    const pendingEdits = draft ? payloadFromDraft(draft, fresh) : undefined;

    pipelineBusyIdRef.current = targetId;
    setActionBusy(true);
    onPipelineStart?.(fresh);
    try {
      const result = await approveAndProcess(
        targetId,
        async () => {
          onUpdated?.();
          await reloadInvoice(targetId);
        },
        pendingEdits
      );
      onUpdated?.();
      if (!isStillViewing(targetId)) return;
      if (pendingEdits) {
        setEditing(false);
        setDraft(null);
      }
      setInv(result.invoice);
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Approve failed");
    } finally {
      if (pipelineBusyIdRef.current === targetId) pipelineBusyIdRef.current = null;
      onPipelineEnd?.(targetId);
      setActionBusy(false);
    }
  }

  async function publish() {
    if (!inv || !invoiceCanPublishToLedger(inv)) return;
    const targetId = inv.id;
    setActionBusy(true);
    try {
      await api.publishInvoice(targetId);
      onUpdated?.();
      await reloadInvoice(targetId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        alert("Not enough credits to post — top up billing or contact an admin.");
      } else {
        alert(e instanceof Error ? e.message : "Posting failed");
      }
    } finally {
      setActionBusy(false);
    }
  }

  return createPortal(
    <div className="pointer-events-none" data-testid="drawer-invoice-detail">
      <button
        type="button"
        data-state={sheetState}
        className="invoice-drawer-backdrop pointer-events-auto"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        data-state={sheetState}
        className="invoice-drawer-panel pointer-events-auto flex h-full flex-col gap-0 border-l border-border bg-card p-0 shadow-lg"
      >
        {loading || !inv ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            {loading ? "Loading document…" : "Document not found"}
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
              <div className="min-w-0 pr-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-base font-semibold truncate">{counterpartyName(inv)}</span>
                  <Badge variant="outline" className="tnum">
                    {documentDisplayRef(inv)}
                  </Badge>
                  <Badge variant="outline" className="tnum text-[10px]">
                    {docNumber}
                  </Badge>
                  {documentTypeBadgeLabel ? (
                    <DocumentTypeChip
                      code={resolvedDocumentTypeCode}
                      label={documentTypeBadgeLabel}
                      display={documentTypeBadgeLabel}
                      title={documentTypeBadgeLabel}
                      purchaseKind={inv?.purchase_document_type}
                      documentTypes={ruleBook?.documentTypes}
                    />
                  ) : null}
                  {inv.evaluation_status ? (
                    <EvaluationStatusBadge status={inv.evaluation_status} invoice={inv} />
                  ) : null}
                  <DuplicateReviewBadge suggested={inv.duplicate_review_suggested} />
                </div>
                {(inv.evaluation_status ?? "").trim() === "line_gl_review" ? (
                  <p className="text-xs text-destructive mt-1">
                    Assign a sub-ledger on each line under the document-type ledger, then save and
                    resume posting.
                  </p>
                ) : null}
                {(inv.evaluation_status ?? "").trim() === "line_items_review" ? (
                  <p className="text-xs text-destructive mt-1">
                    Required line items are missing or unreliable — correct lines on the Lines tab,
                    then continue processing.
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground tnum mt-0.5">
                  {inv.invoice_no ?? "—"} · {inv.invoice_date ?? "—"} · {fmt(inv.total)}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-sm opacity-70 hover:opacity-100"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div
              className="invoice-drawer-body"
              style={{ overscrollBehavior: "contain" }}
            >
              <div className="invoice-drawer-preview-pane bg-muted/40 border-b md:border-b-0 md:border-r border-border p-3 flex flex-col min-h-0">
                <InvoicePreviewModeToggle
                  mode={previewMode}
                  onChange={setPreviewMode}
                  hasOriginal={inv.has_stored_file}
                />
                {previewMode === "original" && inv.has_stored_file ? (
                  <InvoiceDocumentViewer invoiceId={inv.id} className="flex-1 min-h-0" />
                ) : (
                  <div className="flex-1 min-h-0 overflow-y-auto">
                    <DocumentSummaryPreview
                      inv={inv}
                      lineItems={previewLineItems}
                      documentTypeLabel={documentTypeBadgeLabel}
                      absentFields={resolvedDocType?.absentFields ?? []}
                      extractionFieldKeys={extractionFieldKeys}
                      fmt={fmt}
                      tax={tax}
                      sourceKind={sourceKind}
                    />
                  </div>
                )}
                {!inv.has_stored_file && (
                  <div className="mt-3 space-y-2">
                    <p className="text-xs text-muted-foreground">
                      No stored file is linked to this document. Attach a PDF to reprocess or
                      approve.
                    </p>
                    <label className="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-md border border-dashed border-input bg-background px-3 py-2 text-sm shadow-sm hover:bg-muted/50">
                      <input
                        type="file"
                        accept=".pdf,.jpg,.jpeg,.png,.docx,.webp"
                        className="sr-only"
                        disabled={attachBusy}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) void handleAttachPdf(file);
                          e.target.value = "";
                        }}
                      />
                      <FileText className="h-4 w-4" />
                      {attachBusy ? "Uploading…" : "Attach document"}
                    </label>
                  </div>
                )}
              </div>

              <div className="invoice-drawer-detail-pane p-4 md:p-5">
                <PageTabs
                  value={tab}
                  onChange={(v) => selectTab(v as Tab)}
                  secondaryVariant="chevron"
                  tabs={TABS.map((t) => ({
                    value: t,
                    label: tabLabel(t, inv?.route_target, invoiceMatchMode),
                    secondary: t === "overrides" || t === "pipeline",
                  }))}
                />

                {tab === "fields" && inv && (
                  <div className="mt-4 space-y-3">
                    <InvoiceClassificationPanel
                      audit={classificationAudit}
                      loading={classificationLoading}
                      catalogueCodes={catalogueCodes}
                      documentTypes={ruleBook?.documentTypes ?? []}
                      requiresConfirm={classificationConfirmRequired}
                      onConfirmDt={
                        classificationConfirmRequired
                          ? (code) => void resolveClassification(code)
                          : undefined
                      }
                      onChangeDt={
                        classificationConfirmRequired
                          ? (code) => void resolveClassification(code)
                          : undefined
                      }
                    />
                    {extractionFieldKeys.length === 0 ? (
                      <div className="space-y-3">
                        {currencyNeedsSelection(inv) ? (
                          <CurrencySelectRow
                            value={
                              editing && draft
                                ? draft.currency
                                : strField(inv.currency).toUpperCase()
                            }
                            symbolHint={currencySymbolHint}
                            required
                            disabled={actionBusy}
                            onChange={(value) => void handleCurrencySelect(value)}
                          />
                        ) : null}
                      <p className="text-sm text-muted-foreground">
                        {isVisionHeaderPipelineSummary(inv)
                          ? (inv.evaluation_status ?? "").trim() === "vision_header_review"
                            ? "Vision header needs review — complete Fields, save, then Confirm & process."
                            : (inv.evaluation_status ?? "").trim() === "vision_vaulted"
                              ? "Understood path complete — vaulted with header fields only (no OCR / DT extract)."
                              : "Vision header path — open Summary for extracted header fields, or reprocess if they are empty."
                          : classificationConfirmRequired
                          ? "Document type needs review. Confirm or change DT above, then reprocess."
                          : !resolvedDocumentTypeCode
                            ? "No document type is applied yet."
                            : !documentTypeInCatalogue
                              ? `${resolvedDocumentTypeCode} is not in your Rule Book catalogue. Add that document type or confirm a valid DT.`
                              : `No extraction fields configured for ${resolvedDocumentTypeCode}. Set key extraction fields on the document type in Rule Book.`}
                      </p>
                      </div>
                    ) : (
                      <>
                        {isVisionHeaderPipelineSummary(inv) ? (
                          <p className="text-xs text-muted-foreground">
                            Vision path — header fields only. Empty date/total means reprocess so
                            vision extract can fill them; full OCR fields come after DT mapping.
                          </p>
                        ) : null}
                        {(currencyNeedsSelection(inv) ||
                          editing ||
                          extractionFieldKeys.includes("currency")) && (
                          <CurrencySelectRow
                            value={
                              editing && draft
                                ? draft.currency
                                : strField(inv.currency).toUpperCase()
                            }
                            symbolHint={currencySymbolHint}
                            required={currencyNeedsSelection(inv)}
                            disabled={
                              actionBusy ||
                              (!currencyNeedsSelection(inv) &&
                                !canEdit(inv.status) &&
                                !editing)
                            }
                            onChange={(value) => void handleCurrencySelect(value)}
                          />
                        )}
                        {extractionFieldKeys.map((key) =>
                          key === "currency" ? null : (
                        <div key={key}>
                          <FieldRow
                            label={extractionFieldDisplayLabel(key, inv, tax)}
                            value={readExtractionFieldValue(
                              key,
                              inv,
                              draft,
                              Boolean(draft && editing),
                              fmt,
                              extractionFieldKeys,
                              absentFields,
                              sourceKind
                            )}
                            confidence={invoiceFieldConfidence(inv, key)}
                            bold={key === "total"}
                            editable={Boolean(
                              draft && editing && isEditableExtractionField(key, extractionFieldKeys)
                            )}
                            onChange={
                              draft && editing && isEditableExtractionField(key, extractionFieldKeys)
                                ? (value) =>
                                    setDraft(updateDraftExtractionField(draft, key, value))
                                : undefined
                            }
                          />
                          {key === "line_items" && canEdit(inv.status) ? (
                            <button
                              type="button"
                              onClick={openLineItemsForEdit}
                              className="mt-1 text-xs text-primary hover:underline"
                            >
                              {editing ? "Edit line items →" : "Open line items to edit →"}
                            </button>
                          ) : key === "line_items" && drawerLineItems.previewItems.length > 0 ? (
                            <button
                              type="button"
                              onClick={() => setTab("lines")}
                              className="mt-1 text-xs text-primary hover:underline"
                            >
                              View line items tab
                            </button>
                          ) : null}
                        </div>
                          )
                        )}
                      </>
                    )}
                    {extraExtractedFieldKeys.length > 0 ? (
                      <div className="mt-4 space-y-2 border-t border-border pt-3">
                        <p className="text-xs font-medium text-muted-foreground">
                          Additional extracted fields
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Present on the document but not configured on this document type —
                          shown for review only.
                        </p>
                        {extraExtractedFieldKeys.map((key) => (
                          <FieldRow
                            key={`extra-${key}`}
                            label={extractionFieldDisplayLabel(key, inv, tax)}
                            value={readExtractionFieldValue(
                              key,
                              inv,
                              null,
                              false,
                              fmt,
                              extractionFieldKeys,
                              absentFields,
                              sourceKind
                            )}
                            confidence={invoiceFieldConfidence(inv, key)}
                          />
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}

                {tab === "lines" && draft && editing && (
                  <div className="mt-4 space-y-3">
                    <p className="text-xs text-muted-foreground">
                      Edit rows below, then use <span className="font-medium text-foreground">Save changes</span> at the bottom of the drawer.
                    </p>
                    <LineItemsDrawerGrid
                      columns={drawerLineItems.columns}
                      withActions
                      editable
                      showGlAccount
                      inv={inv}
                      postingApplies={postingApplies}
                      parentLedger={parentLedger}
                      draftItems={draft.line_items}
                      onDraftChange={(line_items) => setDraft({ ...draft, line_items })}
                      emptyMessage="No line items — add one below"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          line_items: [...draft.line_items, emptyLineItem()],
                        })
                      }
                    >
                      <Plus className="h-4 w-4 mr-1" />
                      Add line item
                    </Button>
                  </div>
                )}

                {tab === "lines" && !(draft && editing) && inv && (
                  <div className="mt-4">
                    <LineItemsDrawerGrid
                      columns={drawerLineItems.columns}
                      previewItems={drawerLineItems.previewItems}
                      inv={inv}
                      postingApplies={postingApplies}
                      parentLedger={parentLedger}
                      showGlAccount
                      emptyMessage="No line items"
                    />
                  </div>
                )}

                {tab === "po" && (
                  (inv.route_target ?? "").toLowerCase().includes("sales") ? (
                    <InvoiceSalesDossierSection
                      dossier={salesDossier}
                      loading={dossierLoading}
                      customer={inv.vendor ?? undefined}
                      twoWay={isTwoWayMatchMode(invoiceMatchMode)}
                      routeTarget={inv.route_target}
                      onOpenSibling={(id) => setViewId(id)}
                      onMutated={() => {
                        reloadDossier();
                        onUpdated?.();
                      }}
                    />
                  ) : (
                    <InvoicePurchaseDossierSection
                      dossier={dossier}
                      loading={dossierLoading}
                      vendor={inv.vendor ?? undefined}
                      twoWay={isTwoWayMatchMode(invoiceMatchMode)}
                      routeTarget={inv.route_target}
                      onOpenSibling={(id) => setViewId(id)}
                      onMutated={() => {
                        reloadDossier();
                        onUpdated?.();
                      }}
                    />
                  )
                )}

                {tab === "tax" && (
                  <div className="mt-4 space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Subtotal (ex-tax)</span>
                      <span className="tnum">{fmt(inv.subtotal)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">
                        {tax.rate != null ? `${tax.label} ${tax.rate}%` : tax.label}
                      </span>
                      <span className="tnum">{fmt(inv.gst)}</span>
                    </div>
                    <div className="border-t border-border my-2" />
                    <div className="flex justify-between font-semibold">
                      <span>Total (inc-tax)</span>
                      <span className="tnum">{fmt(inv.total)}</span>
                    </div>
                    <p className="text-xs text-muted-foreground pt-2">
                      Tax account: {tax.label} Paid. Currency{" "}
                      {(isSetInvoiceCurrency(inv.currency)
                        ? normalizeCurrencyCode(inv.currency)
                        : null) ||
                        currencySymbolHint ||
                        "not set"}
                      .
                    </p>
                  </div>
                )}

                {tab === "audit" && (
                  <div className="mt-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div
                        className="inline-flex rounded-md border border-border p-0.5"
                        role="tablist"
                        aria-label="Processing path"
                      >
                        {(
                          [
                            ["understood", "Understood"],
                            ["not_understood", "Not understood"],
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={value}
                            type="button"
                            role="tab"
                            aria-selected={auditPathTab === value}
                            data-testid={`processing-path-${value}`}
                            onClick={() => setAuditPathTab(value)}
                            className={cn(
                              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                              auditPathTab === value
                                ? "bg-primary text-primary-foreground"
                                : "text-muted-foreground hover:text-foreground"
                            )}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {auditPathTab === "understood"
                          ? pipelineActivePath === "understood"
                            ? "Active path — capture → vault, then posting when continue runs."
                            : "Vision path stages (may be inactive for this document)."
                          : pipelineActivePath === "not_understood"
                            ? "Active path — OCR / classify → validate → post."
                            : "Legacy OCR path stages (may be inactive for this document)."}
                      </p>
                    </div>
                    {auditLoading ? (
                      <p className="text-sm text-muted-foreground">Loading processing stages…</p>
                    ) : filteredAuditSteps.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No pipeline stages on this path yet.</p>
                    ) : (
                      <ol className="relative border-l border-border ml-2 space-y-4">
                        {filteredAuditSteps.map((step) => (
                          <li key={step.stage} className="ml-4">
                            <span
                              className={cn(
                                "absolute -left-[5px] h-2.5 w-2.5 rounded-full",
                                pipelineDotClass(step.state)
                              )}
                            />
                            <div className="text-sm font-medium">{step.stage}</div>
                            <div className="text-xs text-muted-foreground">
                              {step.when} · {step.detail}
                            </div>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}

                {tab === "overrides" && inv && (
                  <div className="mt-4">
                    <InvoiceProcessingOverridesSection
                      skipSteps={
                        editing && draft
                          ? draft.skip_steps
                          : skipStepsFromInvoice(inv.processing_overrides)
                      }
                      editable={Boolean(editing && draft && canEdit(inv.status))}
                      failedStage={
                        pipelineSteps.find((s) => s.state === "fail")?.stage ??
                        (inv.current_stage_state === "fail" ? inv.current_stage : null)
                      }
                      onToggle={
                        editing && draft && canEdit(inv.status)
                          ? (stepId, run) =>
                              setDraft({
                                ...draft,
                                skip_steps: toggleStepRunning(draft.skip_steps, stepId, run),
                              })
                          : undefined
                      }
                    />
                  </div>
                )}

                {tab === "pipeline" && inv && (
                  <div className="mt-4 space-y-6">
                    {drawerDossierLoading ? (
                      <p className="text-sm text-muted-foreground">Loading dossier pipeline…</p>
                    ) : drawerDossier ? (
                      <DossierPipelineTimeline
                        layout="drawer"
                        pipeline={drawerDossier.pipeline}
                        routeTarget={drawerDossier.routeTarget}
                        pipelinePath={drawerDossier.pipelinePath}
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No dossier pipeline is available for this document yet.
                      </p>
                    )}
                    <div className="border-t border-border pt-4">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                        Pipeline audit (dev)
                      </p>
                      <PipelineDebugPanel invoice={inv} />
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="shrink-0 border-t border-border">
              {inv && settlementHint && canApproveFromDrawer(inv) ? (
                <p
                  className="px-5 pt-2.5 text-xs text-muted-foreground"
                  data-testid="settlement-approval-hint"
                >
                  {settlementHint}
                </p>
              ) : null}
            <div className="flex items-center justify-between gap-2 px-5 py-3">
              {editing ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={actionBusy}
                    onClick={cancelEditing}
                  >
                    Cancel
                  </Button>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      data-testid="button-save-edits"
                      disabled={actionBusy || !draft}
                      onClick={() => void handleSaveEdits()}
                    >
                      {actionBusy ? "Saving…" : "Save changes"}
                    </Button>
                    {inv.status === "rejected" && invoiceCanAttemptReprocess(inv) && (
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="button-reprocess"
                        disabled={actionBusy || !invoiceCanAttemptReprocess(inv)}
                        onClick={() => void handleReprocess()}
                      >
                        Reprocess
                      </Button>
                    )}
                    {canApproveFromDrawer(inv) && (
                      <Button
                        size="sm"
                        data-testid="button-approve-process"
                        disabled={actionBusy || !inv.has_stored_file}
                        onClick={() => void handleApproveAndProcess()}
                      >
                        <Send className="h-4 w-4 mr-1" />
                        Confirm &amp; process
                      </Button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    data-testid="button-reject"
                    disabled={actionBusy || !canRejectClaim(inv.status)}
                    onClick={() => void handleReject()}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Reject
                  </Button>
                  <div className="flex gap-2">
                    {inv.status === "rejected" && invoiceCanAttemptReprocess(inv) && (
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="button-reprocess"
                          disabled={actionBusy || !invoiceCanAttemptReprocess(inv)}
                          onClick={() => void handleReprocess()}
                        >
                          Reprocess
                        </Button>
                      )}
                    {canEdit(inv.status) && (
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="button-edit-invoice"
                        disabled={actionBusy}
                        onClick={startEditing}
                      >
                        <Pencil className="h-4 w-4 mr-1" />
                        Edit
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      data-testid="button-request-approval"
                      disabled={actionBusy || !canRequestInfo(inv.status)}
                      onClick={() => void handleRequestApproval()}
                    >
                      <Clock className="h-4 w-4 mr-1" />
                      Request approval
                    </Button>
                    {canApproveFromDrawer(inv) && (
                      <Button
                        size="sm"
                        data-testid="button-approve-process"
                        disabled={actionBusy || !inv.has_stored_file}
                        onClick={() => void handleApproveAndProcess()}
                      >
                        <Send className="h-4 w-4 mr-1" />
                        Confirm &amp; process
                      </Button>
                    )}
                    {invoiceCanPublishToLedger(inv) && (
                      <Button
                        size="sm"
                        data-testid="button-publish"
                        disabled={actionBusy}
                        onClick={() => void publish()}
                      >
                        <Send className="h-4 w-4 mr-1" />
                        Post to ledger
                      </Button>
                    )}
                  </div>
                </>
              )}
            </div>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body
  );
}
