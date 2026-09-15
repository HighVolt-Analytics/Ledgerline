import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Calendar, Check, Send, Trash2, X } from "lucide-react";
import { api, ApiError, clearGetCache } from "@/api/client";
import type { ApiEnvelope, Invoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Select } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { documentDisplayRef, invoiceMoney } from "@/lib/format";
import { formatDocDate } from "@/lib/allDocumentsSummary";
import { approvalChainCurrentStepRole, approvalChainProgressLabel, approvalChainRecorded, approvalChainRequired, approvalChainToApproverSteps } from "@/lib/approvalQuorum";
import { fetchApprovalsBoard } from "@/lib/invoices";
import {
  approveAndProcess,
  confirmAndProcess,
  invoiceCanAttemptReprocess,
  invoiceHasApprovableSource,
  reprocessAndWatch,
  validateInvoiceReadyForApproval,
} from "@/lib/invoiceActions";
import { useRuleBookDocumentTypes } from "@/hooks/useRuleBookConfig";
import { invoiceCanPublishToLedger } from "@/lib/invoice";
import { documentTypeLabelForCode, invoiceDocumentTypeDisplayLabel, storedDocumentTypeCode } from "@/lib/documentTypeResolve";
import { kpiStatusChipClass, needsReviewStatusChipClass } from "@/lib/kpiModuleColors";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import { UploadColumnProcessingIndicator } from "@/components/upload/UploadColumnCell";
import {
  APPROVAL_QUEUE_STATUSES,
  type ApprovalBoardColumnKey,
  type ApprovedKindFilter,
  canShowApproveOnBoard,
  canShowConfirmOnBoard,
  canShowRejectOnApprovedBoard,
  columnForInvoice,
  filterApprovedBoardRows,
  mergeBoardRowWithLocal,
  PERMANENTLY_DELETABLE,
  systemFiledDocumentTypeOptions,
} from "@/lib/approvalsBoard";
import { ActionChip } from "@/components/ActionChip";
import { cn } from "@/lib/cn";
import { queryKeys, tenantQueryKey } from "@/lib/queryClient";
import { usePermissions } from "@/hooks/usePermissions";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
  API_PORT_HINT,
} from "@/lib/tenantSession";

const APPROVAL_POLL_MS = 90_000;
const APPROVAL_POLL_FAST_MS = 4_000;

const KANBAN_COLUMNS: { key: ApprovalBoardColumnKey; label: string }[] = [
  { key: "pending", label: "To review" },
  { key: "awaiting", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

const APPROVED_KIND_OPTIONS = [
  { value: "all", label: "All" },
  { value: "posted", label: "Posted" },
  { value: "system_filed", label: "System filed" },
] as const;

function upsertInvoice(rows: Invoice[], row: Invoice): Invoice[] {
  const byId = new Map(rows.map((inv) => [inv.id, inv]));
  byId.set(row.id, row);
  return [...byId.values()];
}

function fieldText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function formatSpentForValue(raw: string): string {
  const value = raw.replace(/^spent\s+for:?\s*/i, "").trim();
  if (!value) return "";
  const display = /^myself$/i.test(value) ? "Me" : value;
  return `Spent for ${display}`;
}

function invoiceSpentForLabel(inv: Invoice): string | null {
  const fields = inv.extracted_fields ?? {};
  for (const key of ["spent_for", "spentFor", "spent_choice", "spentChoice"] as const) {
    const text = fieldText(fields[key]);
    if (text) return formatSpentForValue(text);
  }
  const blobs = [
    inv.billing_address,
    fieldText(fields.billing_address),
    fieldText(fields.remarks),
  ];
  for (const blob of blobs) {
    if (!blob) continue;
    const match = blob.match(/Spent for:\s*(.+)/i);
    if (match?.[1]) return formatSpentForValue(match[1].split(/[\n\r]/)[0].trim());
  }
  return null;
}

function approvalCardTitle(
  inv: Invoice,
  documentTypes: Parameters<typeof invoiceDocumentTypeDisplayLabel>[1]
): string {
  const vendor = inv.vendor?.trim();
  if (vendor) return vendor;
  return invoiceDocumentTypeDisplayLabel(inv, documentTypes);
}

function approvalCardStepper(
  inv: Invoice,
  column: ApprovalBoardColumnKey
): { required: number; recorded: number; label: string; percent: number } {
  let required = approvalChainRequired(inv.approval_chain);
  let recorded = approvalChainRecorded(inv.approval_chain);
  if (required <= 0) {
    required = 1;
    recorded = column === "approved" ? 1 : 0;
  }
  const done = Math.min(Math.max(recorded, 0), required);
  const percent =
    required <= 1
      ? done >= 1
        ? 100
        : 0
      : ((done - (done > 0 ? 1 : 0)) / Math.max(required - 1, 1)) * 100;
  return {
    required,
    recorded: done,
    label: `${done} of ${required} approved`,
    percent,
  };
}

function approvalCardTypeChip(
  inv: Invoice,
  documentTypes: Parameters<typeof invoiceDocumentTypeDisplayLabel>[1]
) {
  const code = storedDocumentTypeCode(inv);
  const label = documentTypeLabelForCode(documentTypes ?? [], code) || code || "Not classified";
  return { code: code || undefined, label };
}

function invoiceCardTotal(inv: Invoice): string | number | null {
  if (inv.total != null && String(inv.total).trim() !== "") return inv.total;
  const extracted = inv.extracted_fields?.total;
  if (typeof extracted === "number" && Number.isFinite(extracted)) return extracted;
  return fieldText(extracted) || null;
}

function approvalCardDueLabel(inv: Invoice): string {
  const raw = (inv.due_date ?? "").trim() || fieldText(inv.extracted_fields?.due_date);
  const formatted = formatDocDate(raw);
  if (!formatted || formatted === "—") return "Due —";
  const compact = formatted.replace(/\s+\d{2}$/, "");
  return `Due ${compact}`;
}

function approvalCardAwaitingLabel(inv: Invoice): string | null {
  const lastApproved = [...approvalChainToApproverSteps(inv.approval_chain)]
    .reverse()
    .find((step) => step.state === "approved");
  if (lastApproved?.role) return `${lastApproved.role} approved`;
  const role = approvalChainCurrentStepRole(inv.approval_chain);
  return role ? `${role} approval` : null;
}

function approvalCardDocLabel(inv: Invoice): string {
  return documentDisplayRef(inv);
}

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [boardMeta, setBoardMeta] = useState<ApiEnvelope<Invoice[]>["meta"] | null>(null);
  const [loading, setLoading] = useState(true);
  const { data: documentTypes = [] } = useRuleBookDocumentTypes(!loading);
  const [error, setError] = useState<string | null>(null);
  const { permissions } = usePermissions();
  const canReject = !permissions || permissions.permissions.Approve === true;
  const [toast, setToast] = useState<string | null>(null);
  const [drawerInvoice, setDrawerInvoice] = useState<Invoice | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEditMode, setDrawerEditMode] = useState(false);
  const [drawerEditing, setDrawerEditing] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [processingIds, setProcessingIds] = useState<Set<number>>(() => new Set());
  const [approvedKind, setApprovedKind] = useState<ApprovedKindFilter>("all");
  const [approvedDt, setApprovedDt] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const loadSeq = useRef(0);
  const busyRef = useRef<number | null>(null);
  const processingIdsRef = useRef(processingIds);
  busyRef.current = busyId;
  processingIdsRef.current = processingIds;

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setInvoices([]);
    setBoardMeta(null);
    setLoading(true);
    setError(null);
    setDrawerInvoice(null);
    setDrawerOpen(false);
    setDrawerEditMode(false);
    setBusyId(null);
    setProcessingIds(new Set());
  });

  function openDrawer(inv: Invoice, edit = false) {
    setDrawerInvoice(inv);
    setDrawerEditMode(edit);
    setDrawerOpen(true);
  }

  const pendingInvoiceParam = searchParams.get("invoice");

  useEffect(() => {
    if (!pendingInvoiceParam || loading) return;

    const clearDeepLinkParams = () => {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete("invoice");
      setSearchParams(nextParams, { replace: true });
    };

    const invoiceId = Number(pendingInvoiceParam);
    if (!Number.isFinite(invoiceId) || invoiceId <= 0) {
      clearDeepLinkParams();
      return;
    }

    const inv = invoices.find((row) => row.id === invoiceId);
    if (inv) {
      openDrawer(inv);
    } else {
      setDrawerInvoice({ id: invoiceId } as Invoice);
      setDrawerEditMode(false);
      setDrawerOpen(true);
    }
    clearDeepLinkParams();
  }, [pendingInvoiceParam, loading, invoices, searchParams, setSearchParams]);

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    const fresh = Boolean(options?.fresh);
    if (fresh) clearGetCache();

    try {
      const { rows, meta } = await fetchApprovalsBoard(fresh);
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      const activeProcessing = processingIdsRef.current;
      setBoardMeta(meta);
      setInvoices((prev) => {
        const prevById = new Map(prev.map((inv) => [inv.id, inv]));
        return rows.map((row) =>
          mergeBoardRowWithLocal(row, prevById.get(row.id), activeProcessing)
        );
      });
      if (!options?.silent) setError(null);
    } catch (reason) {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      if (
        handleTenantScopedLoadFailure(reason, {
          retry: () => {
            void load({ silent: true, fresh: true });
          },
        })
      ) {
        return;
      }
      if (!options?.silent) {
        setInvoices([]);
        setBoardMeta(null);
        setError(
          reason instanceof Error
            ? formatTenantLoadError(reason.message, API_PORT_HINT)
            : "Failed to load approvals" + API_PORT_HINT
        );
      }
    } finally {
      if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope) && !options?.silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useVisibilityPolling(() => {
    if (busyRef.current !== null) return;
    return load({ silent: true });
  }, processingIds.size > 0 ? APPROVAL_POLL_FAST_MS : APPROVAL_POLL_MS);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const board = useMemo(() => {
    const cols: Record<ApprovalBoardColumnKey, Invoice[]> = {
      pending: [],
      awaiting: [],
      approved: [],
      rejected: [],
    };
    for (const inv of invoices) {
      cols[columnForInvoice(inv, undefined, processingIds)].push(inv);
    }
    return cols;
  }, [invoices, processingIds]);

  const queueCount = useMemo(
    () => boardMeta?.approval_queue_count ?? invoices.filter((inv) => APPROVAL_QUEUE_STATUSES.has(inv.status)).length,
    [boardMeta, invoices]
  );
  const columnTotals = useMemo(
    () => ({
      pending: boardMeta?.approval_review_count,
      awaiting: boardMeta?.approval_processing_count,
      approved: boardMeta?.approval_approved_count,
      rejected: boardMeta?.approval_rejected_count,
    }),
    [boardMeta]
  );
  const systemFiledDtOptions = useMemo(
    () => systemFiledDocumentTypeOptions(board.approved),
    [board.approved],
  );

  const invalidateAfterApproval = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.payments() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.purchases() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.purchasesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sales() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.salesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: tenantQueryKey(["invoices"]) }),
    ]);
  }, [queryClient]);

  const approveInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv) return;
    if (drawerOpen && drawerInvoice?.id === id && drawerEditing) {
      setToast("Save your edits in the review drawer before approving from the board.");
      return;
    }
    if (!invoiceHasApprovableSource(inv)) {
      setToast("Upload a PDF before approving this invoice.");
      return;
    }
    const fieldCheck = validateInvoiceReadyForApproval(inv, documentTypes);
    if (!fieldCheck.ok) {
      setToast(fieldCheck.message);
      return;
    }
    setBusyId(id);
    setProcessingIds((prev) => new Set(prev).add(id));
    try {
      setToast("Invoice queued for processing…");
      const result = await approveAndProcess(id, () => load({ silent: true, fresh: true }));
      await load({ fresh: true });
      await invalidateAfterApproval();
      if (result.awaitingQuorum) {
        setToast(
          result.quorumLabel
            ? `Approval recorded — ${result.quorumLabel}`
            : "Approval recorded — waiting for additional approvers"
        );
      } else if (result.payment) {
        setToast(`Invoice approved — payment ${result.payment.id} queued for disbursement`);
      } else if (result.collection) {
        setToast(`Invoice approved — collection ${result.collection.id} queued for receipt`);
      } else {
        setToast("Invoice approved — processing complete");
      }
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Approve failed");
      await load({ fresh: true });
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setBusyId(null);
    }
  };

  const escalateInvoice = async (id: number) => {
    if (!canReject) {
      setToast("Your role cannot escalate approvals");
      return;
    }
    const note = window.prompt(
      "Escalate to the next higher role. Note for the next approver:",
      "Unable to approve — escalate to higher role"
    );
    if (note == null) return;
    const trimmed = note.trim();
    if (!trimmed) {
      setToast("Escalation note is required");
      return;
    }
    setBusyId(id);
    try {
      const updated = await api.escalateApproval(id, trimmed);
      await load({ fresh: true });
      const nextLabel = approvalChainProgressLabel(updated.approval_chain);
      setToast(nextLabel ? `Escalated — ${nextLabel}` : "Escalated to the next higher role");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Escalate failed");
    } finally {
      setBusyId(null);
    }
  };

  const confirmInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv) return;
    if (drawerOpen && drawerInvoice?.id === id && drawerEditing) {
      setToast("Save your edits in the review drawer before confirming from the board.");
      return;
    }
    if (!invoiceHasApprovableSource(inv)) {
      setToast("Upload a PDF before confirming this invoice.");
      return;
    }
    const fieldCheck = validateInvoiceReadyForApproval(inv, documentTypes);
    if (!fieldCheck.ok) {
      setToast(fieldCheck.message);
      return;
    }
    setBusyId(id);
    setProcessingIds((prev) => new Set(prev).add(id));
    try {
      setToast("Invoice queued for processing…");
      const result = await confirmAndProcess(id, () => load({ silent: true, fresh: true }));
      await load({ fresh: true });
      await invalidateAfterApproval();
      if (result.awaitingApproval) {
        setToast("Waiting for approval per document-type policy");
      } else if (result.payment) {
        setToast(`Processed — payment ${result.payment.id} queued for disbursement`);
      } else if (result.collection) {
        setToast(`Processed — collection ${result.collection.id} queued for receipt`);
      } else {
        setToast("Processing complete");
      }
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Confirm & process failed");
      await load({ fresh: true });
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setBusyId(null);
    }
  };

  const reprocessInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || inv.status !== "rejected") {
      setToast(
        inv?.status === "duplicate_skipped"
          ? "Duplicate submissions have no stored file — delete permanently or reprocess the original document."
          : "This invoice cannot be reprocessed."
      );
      return;
    }
    if (!invoiceCanAttemptReprocess(inv)) {
      setToast("Upload a PDF before reprocessing this invoice.");
      return;
    }
    setBusyId(id);
    setProcessingIds((prev) => new Set(prev).add(id));
    try {
      setToast("Reprocessing document…");
      await reprocessAndWatch(id, () => load({ silent: true, fresh: true }));
      await load({ fresh: true });
      await invalidateAfterApproval();
      setToast("Reprocess complete — check Processing if the document is still in the pipeline.");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Reprocess failed");
      await load({ fresh: true });
    } finally {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setBusyId(null);
    }
  };

  const rejectInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || (inv.status !== "exception" && inv.status !== "processed")) {
      setToast("This invoice cannot be rejected.");
      return;
    }
    if (!canReject) {
      setToast("Your role does not have permission to reject documents.");
      return;
    }
    if (!window.confirm(`Reject ${inv.vendor ?? documentDisplayRef(inv)}?`)) {
      return;
    }
    setBusyId(id);
    try {
      const rejected = await api.reject(id);
      setInvoices((prev) => upsertInvoice(prev, rejected));
      setToast("Invoice rejected — file moved to rejected storage");
      await invalidateAfterApproval();
      await load({ fresh: true });
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setToast("Your role does not have permission to reject documents.");
      } else {
        setToast(e instanceof Error ? e.message : "Reject failed");
      }
      await load({ fresh: true });
    } finally {
      setBusyId(null);
    }
  };

  const permanentDeleteInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || !PERMANENTLY_DELETABLE.has(inv.status)) {
      setToast("This invoice cannot be permanently deleted.");
      return;
    }
    if (!window.confirm("Do you want to delete it permanently?")) {
      return;
    }
    setBusyId(id);
    try {
      await api.deleteApprovalPermanently(id);
      setInvoices((prev) => prev.filter((i) => i.id !== id));
      if (drawerInvoice?.id === id) {
        setDrawerOpen(false);
        setDrawerInvoice(null);
      }
      setToast("Invoice permanently deleted");
      await invalidateAfterApproval();
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Permanent delete failed");
    } finally {
      setBusyId(null);
    }
  };

  const publish = async (inv: Invoice) => {
    if (!invoiceCanPublishToLedger(inv)) {
      if (inv.published_to_ledger) {
        setToast(`${documentDisplayRef(inv)} is already posted.`);
      } else if (inv.status !== "processed") {
        setToast("Posting is available for processed invoices only.");
      } else {
        setToast("This document type is not eligible for ledger posting.");
      }
      return;
    }
    setBusyId(inv.id);
    try {
      await api.publishInvoice(inv.id);
      setToast(`Posted · ${documentDisplayRef(inv)}`);
      await load({ silent: true, fresh: true });
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        setToast("Not enough credits to post — top up billing or contact an admin.");
      } else {
        setToast(e instanceof Error ? e.message : "Posting failed");
      }
    } finally {
      setBusyId(null);
    }
  };

  if (loading && invoices.length === 0) {
    return (
      <div>
        <PageHeader title="Approvals" />
        <PageLoader variant="kanban" />
      </div>
    );
  }

  if (error && invoices.length === 0) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error}
      </Card>
    );
  }

  if (
    !loading &&
    queueCount === 0 &&
    board.awaiting.length === 0 &&
    board.approved.length === 0 &&
    board.rejected.length === 0
  ) {
    return (
      <div>
        <PageHeader title="Approvals" />
        <EmptyState
          title="Nothing to approve"
          hint="Exception invoices appear here for review. Rejected files are stored under rejected/org/vendor/year/month in Azure."
          action={
            <Link
              to="/upload"
              data-testid="button-load-samples"
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Go to Upload
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div>
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {toast}
        </div>
      )}

      <PageHeader title="Approvals" />

      {error && (
        <Card className="p-3 mb-4 text-xs text-destructive border-destructive/30 bg-destructive/5">
          {error}
        </Card>
      )}

      <div className="approvals-kanban-board">
        {KANBAN_COLUMNS.map((col) => {
          const rawCards = board[col.key];
          const cards =
            col.key === "approved"
              ? filterApprovedBoardRows(rawCards, approvedKind, approvedDt)
              : rawCards;
          const columnCount =
            columnTotals[col.key] == null ||
            (col.key === "approved" && approvedKind !== "all")
              ? cards.length
              : columnTotals[col.key];
          return (
            <section
              key={col.key}
              className={cn("approvals-kanban-column", `approvals-kanban-column--${col.key}`)}
              data-testid={`col-${col.key}`}
            >
              <header className="approvals-kanban-column__header">
                <div className="approvals-kanban-column__heading">
                  <h3 className="approvals-kanban-column__title">{col.label}</h3>
                  <span className="approvals-kanban-column__count">
                    {columnCount} {columnCount === 1 ? "Task" : "Tasks"}
                  </span>
                </div>
                {col.key === "approved" ? (
                  <div
                    className="approvals-kanban-column__filters"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Select
                      size="sm"
                      value={approvedKind}
                      onValueChange={(value) => {
                        setApprovedKind(value as ApprovedKindFilter);
                        if (value !== "system_filed") setApprovedDt("");
                      }}
                      options={[...APPROVED_KIND_OPTIONS]}
                      className="approvals-kanban-column__filter-select"
                      data-testid="filter-approved-kind"
                    />
                    {approvedKind === "system_filed" && systemFiledDtOptions.length > 0 ? (
                      <Select
                        size="sm"
                        value={approvedDt}
                        onValueChange={setApprovedDt}
                        options={[
                          { value: "", label: "All types" },
                          ...systemFiledDtOptions.map((dt) => ({ value: dt, label: dt })),
                        ]}
                        className="approvals-kanban-column__filter-select"
                        data-testid="filter-approved-dt"
                      />
                    ) : null}
                  </div>
                ) : null}
              </header>
              <div className="approvals-kanban-column__cards">
                {cards.map((inv) => {
                  const title = approvalCardTitle(inv, documentTypes);
                  const spentFor = invoiceSpentForLabel(inv);
                  const typeChip = approvalCardTypeChip(inv, documentTypes);
                  const stepper = approvalCardStepper(inv, col.key);
                  const awaiting = approvalCardAwaitingLabel(inv);
                  const busy = busyId === inv.id;
                  return (
                  <article
                    key={inv.id}
                    className="approvals-kanban-card"
                    data-testid={`card-approval-${inv.id}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openDrawer(inv)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openDrawer(inv);
                      }
                    }}
                    aria-label={`Open ${title} ${documentDisplayRef(inv)}`}
                  >
                    <div className="approvals-kanban-card__body">
                      <div className="approvals-kanban-card__heading">
                        <span className="approvals-kanban-card__title" title={title}>
                          {processingIds.has(inv.id) ? <UploadColumnProcessingIndicator /> : null}
                          <span className="approvals-kanban-card__title-text">{title}</span>
                        </span>
                        {spentFor ? (
                          <span
                            className={cn(kpiStatusChipClass("rust"), "approvals-kanban-card__tag")}
                            title={spentFor}
                          >
                            {spentFor}
                          </span>
                        ) : inv.duplicate_review_suggested ? (
                          <span
                            className={cn(needsReviewStatusChipClass(), "approvals-kanban-card__tag")}
                            data-testid={`card-duplicate-review-${inv.id}`}
                            title="Duplicate"
                          >
                            Duplicate
                          </span>
                        ) : (
                          <DocumentTypeChip
                            code={typeChip.code}
                            label={typeChip.label}
                            purchaseKind={inv.purchase_document_type}
                            documentTypes={documentTypes}
                            className="approvals-kanban-card__tag"
                          />
                        )}
                      </div>
                      <p className="approvals-kanban-card__amount tnum">
                        {invoiceMoney(invoiceCardTotal(inv), inv)}
                      </p>
                      <p className="approvals-kanban-card__meta tnum">{approvalCardDocLabel(inv)}</p>
                      {awaiting ? (
                        <p className="approvals-kanban-card__awaiting">{awaiting}</p>
                      ) : null}
                      <p className="approvals-kanban-card__due">
                        <Calendar className="approvals-kanban-card__due-icon" aria-hidden />
                        {approvalCardDueLabel(inv)}
                      </p>
                      <div
                        className="approvals-kanban-card__progress"
                        data-testid={`card-quorum-${inv.id}`}
                      >
                        <span className="approvals-kanban-card__track" aria-hidden>
                          <span className="approvals-kanban-card__track-line" />
                          <span
                            className="approvals-kanban-card__track-fill"
                            style={{
                              width: `calc((100% - 0.5rem) * ${stepper.percent / 100})`,
                            }}
                          />
                          <span
                            className={cn(
                              "approvals-kanban-card__track-knob",
                              stepper.recorded > 0 && "approvals-kanban-card__track-knob--filled"
                            )}
                            style={{
                              left: `calc(0.25rem + (100% - 0.5rem) * ${stepper.percent / 100})`,
                            }}
                          />
                          <span
                            className={cn(
                              "approvals-kanban-card__track-end",
                              stepper.recorded >= stepper.required &&
                                "approvals-kanban-card__track-end--filled"
                            )}
                          />
                        </span>
                        <span className="approvals-kanban-card__quorum tnum">{stepper.label}</span>
                      </div>
                    </div>
                    <div className="approvals-kanban-card__actions">
                      {((col.key === "pending" || col.key === "awaiting") &&
                        (inv.status === "exception" || inv.status === "processed")) ||
                      (col.key === "approved" && canShowRejectOnApprovedBoard(inv)) ? (
                        <ActionChip
                          tone="reject"
                          icon={X}
                          label="Reject"
                          busy={busy}
                          disabled={!canReject}
                          title={
                            canReject
                              ? "Reject"
                              : "Your role does not have permission to reject documents"
                          }
                          onClick={() => void rejectInvoice(inv.id)}
                          testId={`reject-${inv.id}`}
                        />
                      ) : null}
                      {col.key === "pending" && inv.status === "exception" && (
                        <ActionChip
                          tone="edit"
                          icon={ArrowUpRight}
                          label="Escalate"
                          iconOnly
                          busy={busy}
                          disabled={!canReject}
                          title={
                            canReject
                              ? "Escalate"
                              : "Your role cannot escalate approvals"
                          }
                          onClick={() => void escalateInvoice(inv.id)}
                          testId={`escalate-${inv.id}`}
                        />
                      )}
                      {col.key === "approved" && invoiceCanPublishToLedger(inv) && (
                        <ActionChip
                          tone="post"
                          icon={Send}
                          label="Post"
                          iconOnly
                          onClick={() => void publish(inv)}
                          testId={`publish-${inv.id}`}
                        />
                      )}
                      {col.key === "rejected" && PERMANENTLY_DELETABLE.has(inv.status) && (
                        <ActionChip
                          tone="delete"
                          icon={Trash2}
                          label="Delete"
                          onClick={() => void permanentDeleteInvoice(inv.id)}
                          testId={`delete-permanent-${inv.id}`}
                        />
                      )}
                      {canShowConfirmOnBoard(inv, col.key) && (
                        <ActionChip
                          tone="approve"
                          icon={Check}
                          label="Confirm"
                          busy={busy}
                          onClick={() => void confirmInvoice(inv.id)}
                          testId={`confirm-${inv.id}`}
                        />
                      )}
                      {canShowApproveOnBoard(inv, col.key) && (
                        <ActionChip
                          tone="approve"
                          icon={Check}
                          label="Approve"
                          busy={busy}
                          onClick={() => void approveInvoice(inv.id)}
                          testId={`approve-${inv.id}`}
                        />
                      )}
                    </div>
                  </article>
                  );
                })}
                {cards.length === 0 && (
                  <p className="approvals-kanban-empty">Empty</p>
                )}
              </div>
            </section>
          );
        })}
      </div>

      <LazyInvoiceDetailDrawer
        invoiceId={drawerInvoice?.id ?? null}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setDrawerInvoice(null);
          setDrawerEditMode(false);
          setDrawerEditing(false);
        }}
        startInEditMode={drawerEditMode}
        onEditingChange={setDrawerEditing}
        onUpdated={() => load({ fresh: true })}
        onPipelineStart={(invoice) => {
          setProcessingIds((prev) => new Set(prev).add(invoice.id));
        }}
        onPipelineEnd={(invoiceId) => {
          setProcessingIds((prev) => {
            const next = new Set(prev);
            next.delete(invoiceId);
            return next;
          });
        }}
      />
    </div>
  );
}
