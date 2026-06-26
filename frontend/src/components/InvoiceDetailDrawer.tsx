import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  Clock,
  FileText,
  Pencil,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import type { InvoiceDetails, InvoiceClassificationAudit, InvoiceUpdatePayload, LineItem, PipelineAuditStep, PurchaseDossier } from "@/api/types";
import {
  InvoiceDocumentViewer,
  InvoicePreviewModeToggle,
  type PreviewPaneMode,
} from "@/components/InvoiceFilePreview";
import { InvoiceClassificationPanel } from "@/components/invoices/InvoiceClassificationPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { formatQty, documentDisplayRef, vendorInvoiceNo } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  approveAndProcess,
  canApproveClaim,
  canQueuePipeline,
  canRejectClaim,
  canRequestInfo,
  invoiceFieldsFromDetails,
  reprocessAndWatch,
  validateInvoiceFieldsForApproval,
} from "@/lib/invoiceActions";
import {
  invoiceCanPublishToLedger,
  invoiceFieldConfidence,
} from "@/lib/invoice";
import { InvoicePurchaseDossierSection } from "@/components/invoices/InvoicePurchaseDossierSection";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import {
  extractionFieldLabel,
  extractionFieldsForDocumentType,
  isPresetExtractionFieldKey,
  normalizeExtractionFieldKeys,
} from "@/lib/documentExtractionFields";
import {
  documentTypeLabelForCode,
  effectiveDocumentTypeCode,
} from "@/lib/documentTypeResolve";

const TABS = ["fields", "lines", "po", "tax", "audit"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  fields: "Fields",
  lines: "Line items",
  po: "PO Match",
  tax: "Tax",
  audit: "Audit log",
};

const EXPENSE_GL_ACCOUNTS = [
  "Raw Materials",
  "Freight & Logistics",
  "Office Supplies",
  "Professional Services",
  "Contractor Costs",
  "Utilities",
  "Suspense Account",
];

function suggestLineAccount(inv: InvoiceDetails, line: LineItem): string {
  const desc = (line.description ?? "").toLowerCase();
  if (
    desc.includes("steel") ||
    desc.includes("coil") ||
    desc.includes("sheet") ||
    desc.includes("material")
  ) {
    return "Raw Materials";
  }
  if (desc.includes("freight") || desc.includes("logistics") || desc.includes("shipping")) {
    return "Freight & Logistics";
  }
  if (desc.includes("consult") || desc.includes("freelance") || desc.includes("development")) {
    return "Professional Services";
  }
  return inv.account_name ?? "Suspense Account";
}

function lineAccountReason(account: string, vendor: string | null): string {
  if (account === "Suspense Account") return "Awaiting rule book mapping";
  const who = vendor ?? "vendor";
  if (account === "Raw Materials") return `${account} match: ${who} vendor rule`;
  return `${account} match: ${who} keyword rule`;
}

function LineGlAccountCell({
  inv,
  line,
}: {
  inv: InvoiceDetails;
  line: LineItem;
}) {
  const defaultAccount = suggestLineAccount(inv, line);
  const [account, setAccount] = useState(defaultAccount);

  useEffect(() => {
    setAccount(suggestLineAccount(inv, line));
  }, [inv, line]);

  const options = Array.from(
    new Set(
      [
        defaultAccount,
        inv.account_name,
        ...EXPENSE_GL_ACCOUNTS,
        "Suspense Account",
      ].filter((v): v is string => Boolean(v))
    )
  );

  const reason = lineAccountReason(account, inv.vendor);

  return (
    <>
      <Select
        value={account}
        onValueChange={setAccount}
        className="invoice-drawer-gl-select w-full"
        options={options.map((opt) => ({ value: opt, label: opt }))}
        data-testid="invoice-gl-select"
      />
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
        <Sparkles className="h-3 w-3 text-primary shrink-0" />
        <span className="truncate">
          AI: {account} · {reason}
        </span>
      </div>
    </>
  );
}

function formatMoney(
  value: string | null | undefined,
  currency: string
): string {
  if (value == null || value === "") return "—";
  const n = parseFloat(value);
  if (Number.isNaN(n)) return value;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "AUD",
    }).format(n);
  } catch {
    return value;
  }
}

function taxMeta(currency: string): { label: string; rate: number } {
  if (currency === "INR") return { label: "GST", rate: 18 };
  if (currency === "GBP") return { label: "VAT", rate: 20 };
  return { label: "GST", rate: 10 };
}

function extractionFieldDisplayLabel(
  key: string,
  tax: { label: string; rate: number }
): string {
  if (key === "gst") return `${tax.label} ${tax.rate}%`;
  return extractionFieldLabel(key);
}

function isEditableExtractionField(key: string): boolean {
  if (["line_items", "bank_details", "attachment_name", "document_text"].includes(key)) return false;
  if (!isPresetExtractionFieldKey(key)) return false;
  return true;
}

function invoiceScalarValue(inv: InvoiceDetails, key: string): string | null {
  const record = inv as Record<string, unknown>;
  const val = record[key];
  if (val == null) return null;
  const text = String(val).trim();
  return text || null;
}

function readExtractionFieldValue(
  key: string,
  inv: InvoiceDetails,
  draft: InvoiceEditDraft | null,
  editing: boolean,
  fmt: (value: string | null | undefined) => string
): string {
  if (key === "line_items") {
    const count = editing && draft ? draft.line_items.length : inv.line_items.length;
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
  if (editing && draft && isEditableExtractionField(key)) {
    const draftValue = draft[key as keyof InvoiceEditDraft];
    if (typeof draftValue === "string") {
      return draftValue;
    }
  }
  if (key === "subtotal" || key === "gst" || key === "total") {
    if (editing && draft && isEditableExtractionField(key)) {
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
    default:
      return draft;
  }
}

function ConfidenceDot({ value }: { value: number }) {
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

function strField(v: string | null | undefined): string {
  return v ?? "";
}

type LineItemDraft = {
  id?: number;
  description: string;
  qty: string;
  unit_price: string;
  amount: string;
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
  line_items: LineItemDraft[];
};

function draftFromInvoice(inv: InvoiceDetails): InvoiceEditDraft {
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
    line_items: inv.line_items.map((line) => ({
      id: line.id,
      description: strField(line.description),
      qty: strField(line.qty),
      unit_price: strField(line.unit_price),
      amount: strField(line.amount),
    })),
  };
}

function emptyLineItem(): LineItemDraft {
  return { description: "", qty: "", unit_price: "", amount: "" };
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function payloadFromDraft(draft: InvoiceEditDraft): InvoiceUpdatePayload {
  return {
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
    line_items: draft.line_items.map((line) => ({
      id: line.id,
      description: optionalText(line.description),
      qty: optionalText(line.qty),
      unit_price: optionalText(line.unit_price),
      amount: optionalText(line.amount),
    })),
  };
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
  confidence: number;
  bold?: boolean;
  editable?: boolean;
  onChange?: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 items-center">
      <label className="text-xs text-muted-foreground">{label}</label>
      <div className="flex items-center gap-2 min-w-0">
        <Input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            onChange?.(e.target.value);
          }}
          className={cn("h-8 text-sm tnum", bold && "font-semibold")}
          readOnly={!editable}
        />
        {!editable && <ConfidenceDot value={confidence} />}
      </div>
    </div>
  );
}

function canEdit(status: string): boolean {
  return ["exception", "duplicate_skipped", "rejected"].includes(status);
}

function pipelineDotClass(state: "done" | "pending" | "fail" | "skipped"): string {
  if (state === "done") return "bg-[hsl(var(--chart-1))]";
  if (state === "fail") return "bg-destructive";
  return "bg-muted-foreground/40";
}

function InvoiceHtmlPreview({
  inv,
  fmt,
  taxLabel,
  taxRate,
  sourceKind,
}: {
  inv: InvoiceDetails;
  fmt: (v: string | null | undefined) => string;
  taxLabel: string;
  taxRate: number;
  sourceKind: string;
}) {
  const docRef = documentDisplayRef(inv);

  return (
    <div className="invoice-preview-card relative bg-card border border-border rounded-md shadow-sm">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="min-w-0 space-y-1">
          <div className="font-semibold text-base leading-snug">
            {inv.vendor ?? "Unknown vendor"}
          </div>
          {inv.abn && (
            <div className="text-xs text-muted-foreground tnum">{inv.abn}</div>
          )}
          {inv.email_sender && (
            <div className="text-xs text-muted-foreground break-all leading-relaxed">
              {inv.email_sender}
            </div>
          )}
        </div>
        <div className="text-right shrink-0 space-y-0.5">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Invoice
          </div>
          <div className="font-medium tnum">{inv.invoice_no ?? "—"}</div>
          <div className="text-[10px] text-muted-foreground tnum">{docRef}</div>
        </div>
      </div>

      <div className="invoice-preview-meta text-xs">
        <div>
          <span className="text-muted-foreground">Issued:</span>{" "}
          <span className="tnum">{inv.invoice_date ?? "—"}</span>
        </div>
        <div className="text-right">
          <span className="text-muted-foreground">Due:</span>{" "}
          <span className="tnum">{inv.due_date ?? "—"}</span>
        </div>
        {inv.po_reference && (
          <div className="col-span-2">
            <span className="text-muted-foreground">PO:</span>{" "}
            <span className="tnum">{inv.po_reference}</span>
          </div>
        )}
      </div>

      <table className="invoice-preview-table text-xs">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="text-left py-2 font-medium">Description</th>
            <th className="text-right py-2 font-medium">Qty</th>
            <th className="text-right py-2 font-medium">Amount</th>
          </tr>
        </thead>
        <tbody>
          {inv.line_items.length === 0 ? (
            <tr>
              <td colSpan={3} className="py-3 text-muted-foreground">
                No line items
              </td>
            </tr>
          ) : (
            inv.line_items.map((line) => (
              <tr key={line.id} className="border-b border-border/60">
                <td className="py-2.5 align-top">{line.description ?? "—"}</td>
                <td className="py-2.5 align-top tnum">{formatQty(line.qty)}</td>
                <td className="py-2.5 align-top tnum">{fmt(line.amount)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <div className="invoice-preview-totals space-y-1.5 text-xs">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Subtotal</span>
          <span className="tnum">{fmt(inv.subtotal)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">
            {taxLabel} {taxRate}%
          </span>
          <span className="tnum">{fmt(inv.gst)}</span>
        </div>
        <div className="flex justify-between gap-4 font-semibold border-t border-border pt-2 mt-1">
          <span>Total</span>
          <span className="tnum">{fmt(inv.total)}</span>
        </div>
      </div>

      <div className="flex items-center gap-1.5 mt-8 text-[10px] text-muted-foreground">
        <FileText className="h-3 w-3 shrink-0" />
        <span>original.pdf · 1 page · captured via {sourceKind}</span>
      </div>
    </div>
  );
}

type InvoiceDetailDrawerProps = {
  invoiceId: number | null;
  open: boolean;
  onClose: () => void;
  onUpdated?: () => void;
  onPipelineStart?: (invoice: InvoiceDetails) => void;
  onEditingChange?: (editing: boolean) => void;
  startInEditMode?: boolean;
  initialTab?: Tab;
};

export function InvoiceDetailDrawer({
  invoiceId,
  open,
  onClose,
  onUpdated,
  onPipelineStart,
  onEditingChange,
  startInEditMode = false,
  initialTab = "fields",
}: InvoiceDetailDrawerProps) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const { data: ruleBook } = useRuleBookConfig(open);
  const [inv, setInv] = useState<InvoiceDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [sheetState, setSheetState] = useState<"open" | "closed">("closed");
  const [pipelineSteps, setPipelineSteps] = useState<PipelineAuditStep[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [classificationAudit, setClassificationAudit] = useState<InvoiceClassificationAudit | null>(null);
  const [classificationLoading, setClassificationLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<InvoiceEditDraft | null>(null);
  const [attachBusy, setAttachBusy] = useState(false);
  const [previewMode, setPreviewMode] = useState<PreviewPaneMode>("summary");
  const [viewId, setViewId] = useState<number | null>(null);
  const [dossier, setDossier] = useState<PurchaseDossier | null>(null);
  const [dossierLoading, setDossierLoading] = useState(false);

  const activeInvoiceId = viewId ?? invoiceId;

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
    setLoading(true);
    api
      .getInvoice(activeInvoiceId, { fresh: true })
      .then(setInv)
      .catch(() => setInv(null))
      .finally(() => setLoading(false));
  }, [mounted, activeInvoiceId]);

  useEffect(() => {
    if (!inv) {
      setClassificationAudit(null);
      return;
    }
    setClassificationLoading(true);
    api
      .getInvoiceClassificationAudit(inv.id, { fresh: true })
      .then((detail) => {
        setClassificationAudit(detail?.document_type_code ? detail : null);
      })
      .catch(() => setClassificationAudit(null))
      .finally(() => setClassificationLoading(false));
  }, [inv?.id]);

  useEffect(() => {
    if (!inv || tab !== "po") return;
    setDossierLoading(true);
    api
      .getPurchaseDossier(inv.id, { fresh: true })
      .then(setDossier)
      .catch(() => setDossier(null))
      .finally(() => setDossierLoading(false));
  }, [inv, tab]);

  useEffect(() => {
    if (!inv || tab !== "audit") return;
    setAuditLoading(true);
    api
      .getInvoicePipeline(inv.id, { fresh: true })
      .then(setPipelineSteps)
      .catch(() => setPipelineSteps([]))
      .finally(() => setAuditLoading(false));
  }, [inv, tab]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
      setDraft(null);
    }
  }, [open]);

  useEffect(() => {
    onEditingChange?.(editing);
  }, [editing, onEditingChange]);

  useEffect(() => {
    if (!inv) return;
    if (startInEditMode && canEdit(inv.status)) {
      setEditing(true);
      setDraft(draftFromInvoice(inv));
      setTab("fields");
    } else if (!editing) {
      setDraft(null);
    }
  }, [inv, startInEditMode]);

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

  const extractionFieldKeys = useMemo(() => {
    if (!inv) return [];
    const fromApi = normalizeExtractionFieldKeys(inv.document_type_extraction_fields ?? undefined);
    if (fromApi.length) return fromApi;
    if (ruleBook && resolvedDocumentTypeCode) {
      return extractionFieldsForDocumentType(ruleBook.documentTypes, resolvedDocumentTypeCode);
    }
    return [];
  }, [inv, ruleBook, resolvedDocumentTypeCode]);

  const documentTypeInCatalogue = useMemo(() => {
    const code = resolvedDocumentTypeCode;
    if (!code || !ruleBook) return false;
    return ruleBook.documentTypes.some((dt) => dt.code.toUpperCase() === code);
  }, [resolvedDocumentTypeCode, ruleBook]);

  const documentTypeBadgeLabel = useMemo(() => {
    if (!ruleBook) return null;
    if (resolvedDocumentTypeCode) {
      return documentTypeLabelForCode(ruleBook.documentTypes, resolvedDocumentTypeCode);
    }
    const purchase = inv?.purchase_document_type?.trim();
    if (purchase) {
      return purchase.toUpperCase();
    }
    return null;
  }, [inv?.purchase_document_type, resolvedDocumentTypeCode, ruleBook]);

  if (!mounted) return null;

  const tax = inv ? taxMeta(inv.currency) : { label: "GST", rate: 10 };
  const fmt = (v: string | null | undefined) =>
    inv ? formatMoney(v, inv.currency) : "—";
  const sourceKind = inv?.email_sender ? "email" : "upload";
  const docNumber = inv ? (vendorInvoiceNo(inv) ?? documentDisplayRef(inv)) : "—";

  async function reloadInvoice() {
    if (!inv) return;
    const updated = await api.getInvoice(inv.id);
    setInv(updated);
    if (tab === "audit") {
      const steps = await api.getInvoicePipeline(inv.id, { fresh: true });
      setPipelineSteps(steps);
    }
  }

  async function handleSaveEdits() {
    if (!inv || !draft) return;
    setActionBusy(true);
    try {
      const updated = await api.updateInvoice(inv.id, payloadFromDraft(draft));
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

  async function handleAttachPdf(file: File) {
    if (!inv) return;
    setAttachBusy(true);
    try {
      await api.attachInvoiceFile(inv.id, file);
      const updated = await api.getInvoice(inv.id);
      setInv(updated);
      if (editing && draft) {
        setDraft(draftFromInvoice(updated));
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
    setDraft(draftFromInvoice(inv));
    setTab("fields");
  }

  function cancelEditing() {
    setEditing(false);
    setDraft(null);
  }

  function approvalFieldsFromDraftOrInvoice() {
    if (editing && draft) {
      return {
        vendor: draft.vendor,
        total: draft.total,
        due_date: draft.due_date,
      };
    }
    return inv ? invoiceFieldsFromDetails(inv) : { vendor: null, total: null, due_date: null };
  }

  async function handleReject() {
    if (!inv || !canRejectClaim(inv.status)) return;
    if (!window.confirm(`Reject ${inv.vendor ?? documentDisplayRef(inv)}?`)) return;
    setActionBusy(true);
    try {
      await api.reject(inv.id);
      onUpdated?.();
      onClose();
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
    setActionBusy(true);
    try {
      await api.requestApproval(inv.id);
      onUpdated?.();
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Request failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleReprocess() {
    if (!inv || !canQueuePipeline(inv.status)) return;
    if (!inv.has_stored_file) {
      alert("Upload a PDF before reprocessing this invoice.");
      return;
    }
    setActionBusy(true);
    onPipelineStart?.(inv);
    try {
      await reprocessAndWatch(inv.id, async () => {
        onUpdated?.();
        await reloadInvoice();
      });
      onUpdated?.();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Reprocess failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleApproveAndProcess() {
    if (!inv) return;
    const fresh = await api.getInvoice(inv.id, { fresh: true });
    setInv(fresh);
    if (!canApproveClaim(fresh.status)) {
      alert(
        fresh.status === "processed"
          ? "This invoice is already processed. Use Reprocess to run the pipeline again."
          : "This invoice is not in the approval queue."
      );
      return;
    }
    if (!fresh.has_stored_file) {
      alert("Upload a PDF before approving this invoice.");
      return;
    }

    const fieldCheck = validateInvoiceFieldsForApproval(approvalFieldsFromDraftOrInvoice());
    if (!fieldCheck.ok) {
      alert(fieldCheck.message);
      return;
    }

    const pendingEdits = editing && draft ? payloadFromDraft(draft) : undefined;

    setActionBusy(true);
    onPipelineStart?.(fresh);
    try {
      const result = await approveAndProcess(
        inv.id,
        async () => {
          onUpdated?.();
          await reloadInvoice();
        },
        pendingEdits
      );
      if (pendingEdits) {
        setEditing(false);
        setDraft(null);
      }
      setInv(result.invoice);
      onUpdated?.();
      onClose();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setActionBusy(false);
    }
  }

  async function publish() {
    if (!inv || !invoiceCanPublishToLedger(inv)) return;
    setActionBusy(true);
    try {
      await api.publishInvoice(inv.id);
      onUpdated?.();
      await reloadInvoice();
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
        className="invoice-drawer-panel pointer-events-auto flex h-full flex-col gap-0 border-l border-border bg-background p-0 shadow-lg"
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
                  <span className="text-base font-semibold truncate">{inv.vendor ?? "—"}</span>
                  <Badge variant="outline" className="tnum">
                    {documentDisplayRef(inv)}
                  </Badge>
                  <Badge variant="outline" className="tnum text-[10px]">
                    {docNumber}
                  </Badge>
                  {documentTypeBadgeLabel ? (
                    <Badge className="bg-accent text-accent-foreground border-0 text-[10px]">
                      {documentTypeBadgeLabel}
                    </Badge>
                  ) : null}
                </div>
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
                    <InvoiceHtmlPreview
                      inv={inv}
                      fmt={fmt}
                      taxLabel={tax.label}
                      taxRate={tax.rate}
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
                        accept=".pdf,.jpg,.jpeg,.png,.docx"
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
                <div
                  role="tablist"
                  className="inline-flex h-10 flex-wrap items-center justify-center rounded-md bg-muted p-1 text-muted-foreground"
                >
                  {TABS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      role="tab"
                      aria-selected={tab === t}
                      onClick={() => setTab(t)}
                      className={cn(
                        "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all",
                        tab === t
                          ? "bg-background text-foreground shadow-sm"
                          : "hover:text-foreground"
                      )}
                    >
                      {TAB_LABELS[t]}
                    </button>
                  ))}
                </div>

                {tab === "fields" && inv && (
                  <div className="mt-4 space-y-3">
                    <InvoiceClassificationPanel
                      audit={classificationAudit}
                      loading={classificationLoading}
                    />
                    {extractionFieldKeys.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {!resolvedDocumentTypeCode
                          ? "No document type matched. Configure classifiers in Rule Book → Document types, then reprocess."
                          : !documentTypeInCatalogue
                            ? `${resolvedDocumentTypeCode} is not in your Rule Book catalogue. Add that document type or reprocess after fixing classifiers.`
                            : `No extraction fields configured for ${resolvedDocumentTypeCode}. Set key extraction fields on the document type card in Rule Book.`}
                      </p>
                    ) : (
                      extractionFieldKeys.map((key) => (
                        <div key={key}>
                          <FieldRow
                            label={extractionFieldDisplayLabel(key, tax)}
                            value={readExtractionFieldValue(
                              key,
                              inv,
                              draft,
                              Boolean(draft && editing),
                              fmt
                            )}
                            confidence={invoiceFieldConfidence(inv, key)}
                            bold={key === "total"}
                            editable={Boolean(
                              draft && editing && isEditableExtractionField(key)
                            )}
                            onChange={
                              draft && editing && isEditableExtractionField(key)
                                ? (value) =>
                                    setDraft(updateDraftExtractionField(draft, key, value))
                                : undefined
                            }
                          />
                          {key === "line_items" && inv.line_items.length > 0 ? (
                            <button
                              type="button"
                              onClick={() => setTab("lines")}
                              className="mt-1 text-xs text-primary hover:underline"
                            >
                              View line items tab
                            </button>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {tab === "lines" && draft && editing && (
                  <div className="mt-4 space-y-3">
                    <div className="overflow-x-auto rounded-md border border-border">
                      <table className="invoice-drawer-lines-table w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted-foreground bg-muted/50">
                            <th className="px-3 py-2 font-medium">Description</th>
                            <th className="px-2 py-2 font-medium text-right">Qty</th>
                            <th className="px-2 py-2 font-medium text-right whitespace-nowrap">
                              Unit
                            </th>
                            <th className="px-2 py-2 font-medium text-right whitespace-nowrap">
                              Total
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {draft.line_items.length === 0 ? (
                            <tr>
                              <td
                                colSpan={4}
                                className="px-3 py-6 text-center text-sm text-muted-foreground"
                              >
                                No line items — add one below
                              </td>
                            </tr>
                          ) : (
                            draft.line_items.map((line, index) => (
                              <tr key={line.id ?? `new-${index}`} className="border-t border-border align-top">
                                <td className="px-2 py-2">
                                  <Input
                                    value={line.description}
                                    onChange={(e) => {
                                      const next = [...draft.line_items];
                                      next[index] = { ...line, description: e.target.value };
                                      setDraft({ ...draft, line_items: next });
                                    }}
                                    className="h-8 text-sm"
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <Input
                                    value={line.qty}
                                    onChange={(e) => {
                                      const next = [...draft.line_items];
                                      next[index] = { ...line, qty: e.target.value };
                                      setDraft({ ...draft, line_items: next });
                                    }}
                                    className="h-8 text-sm text-right tnum"
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <Input
                                    value={line.unit_price}
                                    onChange={(e) => {
                                      const next = [...draft.line_items];
                                      next[index] = { ...line, unit_price: e.target.value };
                                      setDraft({ ...draft, line_items: next });
                                    }}
                                    className="h-8 text-sm text-right tnum"
                                  />
                                </td>
                                <td className="px-2 py-2">
                                  <Input
                                    value={line.amount}
                                    onChange={(e) => {
                                      const next = [...draft.line_items];
                                      next[index] = { ...line, amount: e.target.value };
                                      setDraft({ ...draft, line_items: next });
                                    }}
                                    className="h-8 text-sm text-right tnum"
                                  />
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
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

                {tab === "lines" && !(draft && editing) && (
                  <div className="mt-4 overflow-x-auto rounded-md border border-border">
                    <table className="invoice-drawer-lines-table w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-muted-foreground bg-muted/50">
                          <th className="px-3 py-2 font-medium">Description</th>
                          <th className="px-2 py-2 font-medium text-right">Qty</th>
                          <th className="px-2 py-2 font-medium text-right whitespace-nowrap">
                            Unit
                          </th>
                          <th className="px-2 py-2 font-medium text-right whitespace-nowrap">
                            Total
                          </th>
                          <th className="px-3 py-2 font-medium">GL account</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inv.line_items.length === 0 ? (
                          <tr>
                            <td
                              colSpan={5}
                              className="px-3 py-6 text-center text-sm text-muted-foreground"
                            >
                              No line items
                            </td>
                          </tr>
                        ) : (
                          inv.line_items.map((line) => (
                            <tr key={line.id} className="border-t border-border align-top">
                              <td className="px-3 py-2">
                                {line.description ?? "—"}
                              </td>
                              <td className="px-2 py-2 text-right tnum whitespace-nowrap">
                                {formatQty(line.qty)}
                              </td>
                              <td className="px-2 py-2 text-right tnum whitespace-nowrap">
                                {fmt(line.unit_price)}
                              </td>
                              <td className="px-2 py-2 text-right tnum whitespace-nowrap">
                                {fmt(line.amount)}
                              </td>
                              <td className="px-3 py-2">
                                <LineGlAccountCell inv={inv} line={line} />
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                )}

                {tab === "po" && (
                  <InvoicePurchaseDossierSection
                    dossier={dossier}
                    loading={dossierLoading}
                    onOpenSibling={(id) => setViewId(id)}
                  />
                )}

                {tab === "tax" && (
                  <div className="mt-4 space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Subtotal (ex-tax)</span>
                      <span className="tnum">{fmt(inv.subtotal)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">
                        {tax.label} {tax.rate}%
                      </span>
                      <span className="tnum">{fmt(inv.gst)}</span>
                    </div>
                    <div className="border-t border-border my-2" />
                    <div className="flex justify-between font-semibold">
                      <span>Total (inc-tax)</span>
                      <span className="tnum">{fmt(inv.total)}</span>
                    </div>
                    <p className="text-xs text-muted-foreground pt-2">
                      Tax account: GST Paid. Currency {inv.currency}.
                    </p>
                  </div>
                )}

                {tab === "audit" && (
                  <div className="mt-4">
                    {auditLoading ? (
                      <p className="text-sm text-muted-foreground">Loading audit log…</p>
                    ) : (
                      <ol className="relative border-l border-border ml-2 space-y-4">
                        {pipelineSteps.map((step) => (
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
              </div>
            </div>

            <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-border shrink-0">
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
                  <Button
                    size="sm"
                    data-testid="button-save-edits"
                    disabled={actionBusy || !draft}
                    onClick={() => void handleSaveEdits()}
                  >
                    {actionBusy ? "Saving…" : "Save changes"}
                  </Button>
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
                    {canQueuePipeline(inv.status) && (
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid="button-reprocess"
                          disabled={actionBusy || !inv.has_stored_file}
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
                    {canApproveClaim(inv.status) && (
                      <Button
                        size="sm"
                        data-testid="button-approve-process"
                        disabled={actionBusy || !inv.has_stored_file}
                        onClick={() => void handleApproveAndProcess()}
                      >
                        <Send className="h-4 w-4 mr-1" />
                        Approve &amp; process
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
          </>
        )}
      </div>
    </div>,
    document.body
  );
}
