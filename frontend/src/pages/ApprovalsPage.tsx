import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Pencil, RefreshCw, Send, Trash2, X } from "lucide-react";
import { api, ApiError, clearGetCache } from "@/api/client";
import type { Invoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { EvaluationStatusBadge } from "@/components/inbox/EvaluationStatusBadge";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { documentDisplayRef, money } from "@/lib/format";
import { fetchApprovalsBoard } from "@/lib/invoices";
import { approveAndProcess, invoiceCanAttemptReprocess, invoiceFieldsFromDetails, reprocessAndWatch, validateInvoiceFieldsForApproval, watchProcessingUntilIdle } from "@/lib/invoiceActions";
import { invoiceCanPublishToLedger } from "@/lib/invoice";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import {
  APPROVABLE_STATUSES,
  APPROVAL_QUEUE_STATUSES,
  type ApprovalBoardColumnKey,
  canShowReprocessOnBoard,
  columnForInvoice,
  mergeBoardRowWithLocal,
  PERMANENTLY_DELETABLE,
  needsReviewQueueCount,
  isNeedsReviewInvoice,
} from "@/lib/approvalsBoard";
import { ActionChip } from "@/components/ActionChip";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/queryClient";
import { usePermissions } from "@/hooks/usePermissions";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
  API_PORT_HINT,
} from "@/lib/tenantSession";

const APPROVAL_POLL_MS = 15_000;

const KANBAN_COLUMNS: { key: ApprovalBoardColumnKey; label: string }[] = [
  { key: "pending", label: "To review" },
  { key: "awaiting", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

function upsertInvoice(rows: Invoice[], row: Invoice): Invoice[] {
  const byId = new Map(rows.map((inv) => [inv.id, inv]));
  byId.set(row.id, row);
  return [...byId.values()];
}

function docNumber(inv: Invoice): string {
  return documentDisplayRef(inv);
}

export function ApprovalsPage() {
  const queryClient = useQueryClient();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { permissions } = usePermissions();
  const canReject = !permissions || permissions.permissions.Reject === true;
  const [toast, setToast] = useState<string | null>(null);
  const [drawerInvoice, setDrawerInvoice] = useState<Invoice | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEditMode, setDrawerEditMode] = useState(false);
  const [drawerEditing, setDrawerEditing] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [processingIds, setProcessingIds] = useState<Set<number>>(() => new Set());
  const [processingBusy, setProcessingBusy] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const loadSeq = useRef(0);
  const busyRef = useRef<number | null>(null);
  const processingIdsRef = useRef(processingIds);
  busyRef.current = busyId;
  processingIdsRef.current = processingIds;

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setInvoices([]);
    setLoading(true);
    setError(null);
    setDrawerInvoice(null);
    setDrawerOpen(false);
    setDrawerEditMode(false);
    setSearchQuery("");
    setBusyId(null);
    setProcessingIds(new Set());
  });

  function openDrawer(inv: Invoice, edit = false) {
    setDrawerInvoice(inv);
    setDrawerEditMode(edit);
    setDrawerOpen(true);
  }

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    const fresh = options?.fresh ?? !options?.silent;
    if (fresh) clearGetCache();

    try {
      const rows = await fetchApprovalsBoard(fresh);
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      const activeProcessing = processingIdsRef.current;
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

  const runProcessing = async () => {
    setProcessingBusy(true);
    setToast(null);
    try {
      await api.triggerProcess();
      await watchProcessingUntilIdle(async () => {
        await load({ silent: true, fresh: true });
      });
      setToast("Processing finished — refresh the board if cards did not move.");
      await load({ fresh: true });
    } catch (e) {
      setToast(
        (e instanceof Error ? e.message : "Processing failed") +
          " Start the Celery worker in backend (see terminal)."
      );
    } finally {
      setProcessingBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, [load]);

  useVisibilityPolling(() => {
    if (busyRef.current !== null) return;
    void load({ silent: true, fresh: true });
  }, APPROVAL_POLL_MS);

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
      if (!invoiceMatchesListSearch(inv, searchQuery)) continue;
      cols[columnForInvoice(inv, undefined, processingIds)].push(inv);
    }
    return cols;
  }, [invoices, searchQuery, processingIds]);

  const queueCount = useMemo(
    () => invoices.filter((inv) => APPROVAL_QUEUE_STATUSES.has(inv.status)).length,
    [invoices]
  );
  const needsReviewCount = useMemo(() => needsReviewQueueCount(invoices), [invoices]);

  const invalidateAfterApproval = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.payments() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
    ]);
  }, [queryClient]);

  const approveInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv) return;
    if (drawerOpen && drawerInvoice?.id === id && drawerEditing) {
      setToast("Save your edits in the review drawer before approving from the board.");
      return;
    }
    if (!inv.has_stored_file) {
      setToast("Upload a PDF before approving this invoice.");
      return;
    }
    const fieldCheck = validateInvoiceFieldsForApproval(invoiceFieldsFromDetails(inv));
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
      if (result.payment) {
        setToast(`Invoice approved — payment ${result.payment.id} queued for disbursement`);
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

  const runNeedsReviewProcessing = async () => {
    const targets = invoices.filter(
      (inv) =>
        isNeedsReviewInvoice(inv) &&
        columnForInvoice(inv, undefined, processingIds) === "awaiting" &&
        APPROVABLE_STATUSES.has(inv.status)
    );
    if (!targets.length) {
      setToast("No needs-review documents in Processing to advance.");
      return;
    }
    setProcessingBusy(true);
    try {
      for (const inv of targets) {
        await approveInvoice(inv.id);
      }
      setToast(
        `Queued ${targets.length} needs-review document${targets.length === 1 ? "" : "s"} for processing.`
      );
      await load({ fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Needs-review processing failed");
    } finally {
      setProcessingBusy(false);
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
        <PageHeader title="Approvals" subtitle="Review and approve invoices — live data from the API." />
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
        <PageHeader
          title="Approvals"
          subtitle="Review and approve invoices — live data from the API."
        />
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

      <PageHeader
        title="Approvals"
        subtitle={`${queueCount} in approval queue · reject moves files to rejected/org/vendor/year/month`}
        actions={
          <Button
            variant="surface"
            size="sm"
            onClick={() => load({ fresh: true })}
            disabled={loading}
            aria-label="Refresh approvals"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </Button>
        }
      />

      {error && (
        <Card className="p-3 mb-4 text-xs text-destructive border-destructive/30 bg-destructive/5">
          {error}
        </Card>
      )}

      {needsReviewCount > 0 && (
        <Card className="p-3 mb-4 text-xs border-amber-500/40 bg-amber-500/10 flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground">
            {needsReviewCount} document{needsReviewCount === 1 ? "" : "s"} flagged{" "}
            <span className="font-medium text-foreground">needs review</span> after classification
            (vendor drift, field confidence, or policy disagreement).
          </p>
          <Button
            variant="outline"
            size="sm"
            disabled={processingBusy}
            onClick={() => void runNeedsReviewProcessing()}
            data-testid="button-run-needs-review"
          >
            {processingBusy ? "Processing…" : "Process needs-review queue"}
          </Button>
        </Card>
      )}

      {board.awaiting.length > 0 && (
        <Card className="p-3 mb-4 text-xs border-border bg-muted/40 flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground">
            {board.awaiting.length} document{board.awaiting.length === 1 ? "" : "s"} in the
            pipeline (parse → validate → map → journal). Click Run processing if they
            do not advance automatically.
          </p>
          <Button
            variant="default"
            size="sm"
            disabled={processingBusy}
            onClick={() => void runProcessing()}
            data-testid="button-run-processing"
          >
            {processingBusy ? "Processing…" : "Run processing"}
          </Button>
        </Card>
      )}

      <div className="mb-4 flex justify-end">
        <ListSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search this list…"
          testId="input-approvals-search"
        />
      </div>

      <div className="approvals-kanban-board">
        {KANBAN_COLUMNS.map((col) => {
          const cards = board[col.key];
          return (
            <section
              key={col.key}
              className="approvals-kanban-column"
              data-testid={`col-${col.key}`}
            >
              <header className="approvals-kanban-column__header">
                <h3 className="approvals-kanban-column__title">{col.label}</h3>
                <span className="approvals-kanban-column__count">
                  {cards.length} {cards.length === 1 ? "Task" : "Tasks"}
                </span>
              </header>
              <div className="approvals-kanban-column__cards">
                {cards.map((inv) => (
                  <article
                    key={inv.id}
                    className="approvals-kanban-card"
                    data-testid={`card-approval-${inv.id}`}
                    onClick={() => openDrawer(inv)}
                  >
                    <div className="approvals-kanban-card__top">
                      <span className="approvals-kanban-card__vendor">{inv.vendor ?? "—"}</span>
                      <span className="approvals-kanban-card__ref">{documentDisplayRef(inv)}</span>
                    </div>
                    <div className="approvals-kanban-card__subline-row">
                      <p className="approvals-kanban-card__meta tnum">
                        {docNumber(inv)} · {money(inv.total, inv.currency)}
                        {col.key === "awaiting" && (
                          <span className="ml-1 capitalize">· {inv.status.replace(/_/g, " ")}</span>
                        )}
                      </p>
                      {inv.evaluation_status === "needs_review" && (
                        <span
                          className="approvals-kanban-card__review-pill"
                          title="Needs review"
                          aria-label="Needs review"
                          data-testid={`needs-review-${inv.id}`}
                        >
                          <AlertTriangle aria-hidden />
                          Review
                        </span>
                      )}
                    </div>
                    {col.key === "awaiting" && inv.evaluation_status ? (
                      <div className="mt-1.5">
                        <EvaluationStatusBadge
                          status={inv.evaluation_status}
                          reviewReasons={
                            isNeedsReviewInvoice(inv) ? ["Flagged for manual review"] : undefined
                          }
                        />
                      </div>
                    ) : null}
                    {col.key === "pending" && inv.evaluation_status ? (
                      <div className="mt-1.5">
                        <EvaluationStatusBadge status={inv.evaluation_status} />
                      </div>
                    ) : null}
                    <div
                      className="approvals-kanban-card__actions"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {canShowReprocessOnBoard(inv, col.key) && (
                        <ActionChip
                          tone="reprocess"
                          icon={RefreshCw}
                          label={busyId === inv.id ? "…" : "Reprocess"}
                          disabled={busyId === inv.id}
                          onClick={() => void reprocessInvoice(inv.id)}
                          testId={`reprocess-${inv.id}`}
                        />
                      )}
                      {col.key === "rejected" && inv.status === "duplicate_skipped" && (
                        <span className="text-[10px] text-muted-foreground leading-tight">
                          Duplicate — no file stored
                        </span>
                      )}
                      {col.key === "pending" && APPROVABLE_STATUSES.has(inv.status) && (
                        <ActionChip
                          tone="edit"
                          icon={Pencil}
                          label="Edit"
                          onClick={() => openDrawer(inv, true)}
                          testId={`edit-${inv.id}`}
                        />
                      )}
                      {col.key !== "approved" && APPROVABLE_STATUSES.has(inv.status) && (
                        <ActionChip
                          tone="approve"
                          icon={Check}
                          label={busyId === inv.id ? "…" : "Approve"}
                          disabled={busyId === inv.id}
                          onClick={() => void approveInvoice(inv.id)}
                          testId={`approve-${inv.id}`}
                        />
                      )}
                      {col.key === "pending" && inv.status === "exception" && (
                        <ActionChip
                          tone="reject"
                          icon={X}
                          label="Reject"
                          disabled={busyId === inv.id || !canReject}
                          title={canReject ? undefined : "Your role cannot reject documents"}
                          onClick={() => void rejectInvoice(inv.id)}
                          testId={`reject-${inv.id}`}
                        />
                      )}
                      {col.key === "approved" && inv.status === "processed" && (
                        <ActionChip
                          tone="reject"
                          icon={X}
                          label="Reject"
                          disabled={busyId === inv.id || !canReject}
                          title={canReject ? undefined : "Your role cannot reject documents"}
                          onClick={() => void rejectInvoice(inv.id)}
                          testId={`reject-${inv.id}`}
                        />
                      )}
                      {col.key === "approved" && invoiceCanPublishToLedger(inv) && (
                        <ActionChip
                          tone="post"
                          icon={Send}
                          label="Post"
                          onClick={() => void publish(inv)}
                          testId={`publish-${inv.id}`}
                        />
                      )}
                      {col.key === "rejected" && PERMANENTLY_DELETABLE.has(inv.status) && (
                        <ActionChip
                          tone="delete"
                          icon={Trash2}
                          label={busyId === inv.id ? "…" : "Delete"}
                          disabled={busyId === inv.id}
                          onClick={() => void permanentDeleteInvoice(inv.id)}
                          testId={`delete-permanent-${inv.id}`}
                        />
                      )}
                    </div>
                  </article>
                ))}
                {cards.length === 0 && (
                  <p className="approvals-kanban-empty">Empty</p>
                )}
              </div>
            </section>
          );
        })}
      </div>

      <InvoiceDetailDrawer
        invoiceId={drawerInvoice?.id ?? null}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
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
