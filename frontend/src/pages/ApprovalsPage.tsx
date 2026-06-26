import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, RefreshCw, Send, Trash2, X } from "lucide-react";
import { api, ApiError, clearGetCache } from "@/api/client";
import type { Invoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { documentDisplayRef, money } from "@/lib/format";
import { fetchApprovalsBoard } from "@/lib/invoices";
import { approveAndProcess, invoiceFieldsFromDetails, validateInvoiceFieldsForApproval, watchProcessingUntilIdle } from "@/lib/invoiceActions";
import { invoiceCanPublishToLedger } from "@/lib/invoice";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/queryClient";
import { usePermissions } from "@/hooks/usePermissions";

const APPROVAL_POLL_MS = 15_000;
const API_HINT = " Ensure the API is running on port 8001.";

const COLUMNS = [
  { key: "pending", label: "To review" },
  { key: "awaiting", label: "Processing" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
] as const;

type ColumnKey = (typeof COLUMNS)[number]["key"];

const PIPELINE_STATUSES = new Set([
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
]);

const APPROVAL_QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

const APPROVABLE_STATUSES = new Set(["exception", "rejected", "duplicate_skipped"]);

const PERMANENTLY_DELETABLE = new Set(["rejected", "duplicate_skipped"]);

function upsertInvoice(rows: Invoice[], row: Invoice): Invoice[] {
  const byId = new Map(rows.map((inv) => [inv.id, inv]));
  byId.set(row.id, row);
  return [...byId.values()];
}

function columnForInvoice(inv: Invoice, processingIds: ReadonlySet<number>): ColumnKey {
  if (processingIds.has(inv.id) || PIPELINE_STATUSES.has(inv.status)) return "awaiting";
  if (inv.status === "rejected" || inv.status === "duplicate_skipped") return "rejected";
  if (inv.status === "processed") return "approved";
  if (inv.status === "exception") return "pending";
  return "pending";
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
  busyRef.current = busyId;

  function openDrawer(inv: Invoice, edit = false) {
    setDrawerInvoice(inv);
    setDrawerEditMode(edit);
    setDrawerOpen(true);
  }

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    const seq = ++loadSeq.current;
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    const fresh = options?.fresh ?? !options?.silent;
    if (fresh) clearGetCache();

    try {
      const rows = await fetchApprovalsBoard(fresh);
      if (seq !== loadSeq.current) return;
      setInvoices(rows);
      if (!options?.silent) setError(null);
    } catch (reason) {
      if (seq !== loadSeq.current) return;
      if (!options?.silent) {
        setInvoices([]);
        setError(
          reason instanceof Error
            ? reason.message + API_HINT
            : "Failed to load approvals" + API_HINT
        );
      }
    } finally {
      if (seq === loadSeq.current && !options?.silent) {
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
    const cols: Record<ColumnKey, Invoice[]> = {
      pending: [],
      awaiting: [],
      approved: [],
      rejected: [],
    };
    for (const inv of invoices) {
      if (!invoiceMatchesListSearch(inv, searchQuery)) continue;
      cols[columnForInvoice(inv, processingIds)].push(inv);
    }
    return cols;
  }, [invoices, searchQuery, processingIds]);

  const queueCount = useMemo(
    () => invoices.filter((inv) => APPROVAL_QUEUE_STATUSES.has(inv.status)).length,
    [invoices]
  );

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
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading approvals…</Card>
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
            variant="outline"
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

      {board.awaiting.length > 0 && (
        <Card className="p-3 mb-4 text-xs border-border bg-muted/40 flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground">
            {board.awaiting.length} document{board.awaiting.length === 1 ? "" : "s"} in the
            pipeline (parse → validate → map → journal). Click Run processing if they
            do not advance automatically.
          </p>
          <Button
            variant="outline"
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

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {COLUMNS.map((col) => {
          const cards = board[col.key];
          return (
            <Card
              key={col.key}
              className="p-3 bg-muted/30 min-h-[240px]"
              data-testid={`col-${col.key}`}
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold">{col.label}</h3>
                <Badge variant="outline" className="tnum text-[10px]">
                  {cards.length}
                </Badge>
              </div>
              <div className="space-y-2">
                {cards.map((inv) => (
                  <Card
                    key={inv.id}
                    className="p-3 cursor-pointer hover-elevate shadow-sm flex flex-col min-h-[120px]"
                    data-testid={`card-approval-${inv.id}`}
                    onClick={() => openDrawer(inv)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate">{inv.vendor ?? "—"}</span>
                      <Badge variant="outline" className="tnum text-[10px] shrink-0">
                        {documentDisplayRef(inv)}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground tnum mt-0.5">
                      {docNumber(inv)} · {money(inv.total, inv.currency)}
                      {col.key === "awaiting" && (
                        <span className="ml-1 capitalize">· {inv.status.replace(/_/g, " ")}</span>
                      )}
                    </div>
                    <div
                      className="flex items-center gap-1 mt-2 flex-wrap"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {col.key === "pending" && APPROVABLE_STATUSES.has(inv.status) && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-1.5 text-[11px]"
                          onClick={() => openDrawer(inv, true)}
                          data-testid={`edit-${inv.id}`}
                        >
                          <Pencil className="h-3 w-3 mr-0.5" />
                          Edit
                        </Button>
                      )}
                      {col.key !== "approved" && APPROVABLE_STATUSES.has(inv.status) && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-1.5 text-[11px] text-[hsl(var(--chart-1))]"
                          disabled={busyId === inv.id}
                          onClick={() => void approveInvoice(inv.id)}
                          data-testid={`approve-${inv.id}`}
                        >
                          <Check className="h-3 w-3 mr-0.5" />
                          {busyId === inv.id ? "…" : "Approve"}
                        </Button>
                      )}
                      {col.key === "pending" && inv.status === "exception" && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                          disabled={busyId === inv.id || !canReject}
                          title={canReject ? undefined : "Your role cannot reject documents"}
                          onClick={() => void rejectInvoice(inv.id)}
                          data-testid={`reject-${inv.id}`}
                        >
                          <X className="h-3 w-3 mr-0.5" />
                          Reject
                        </Button>
                      )}
                      {col.key === "approved" && inv.status === "processed" && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                          disabled={busyId === inv.id || !canReject}
                          title={canReject ? undefined : "Your role cannot reject documents"}
                          onClick={() => void rejectInvoice(inv.id)}
                          data-testid={`reject-${inv.id}`}
                        >
                          <X className="h-3 w-3 mr-0.5" />
                          Reject
                        </Button>
                      )}
                      {col.key === "approved" && invoiceCanPublishToLedger(inv) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-1.5 text-[11px] text-primary"
                          onClick={() => void publish(inv)}
                          data-testid={`publish-${inv.id}`}
                        >
                          <Send className="h-3 w-3 mr-0.5" />
                          Post
                        </Button>
                      )}
                      {col.key === "rejected" && PERMANENTLY_DELETABLE.has(inv.status) && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 px-1.5 text-[11px] text-destructive border-destructive/40"
                          disabled={busyId === inv.id}
                          onClick={() => void permanentDeleteInvoice(inv.id)}
                          data-testid={`delete-permanent-${inv.id}`}
                        >
                          <Trash2 className="h-3 w-3 mr-0.5" />
                          {busyId === inv.id ? "…" : "Delete permanently"}
                        </Button>
                      )}
                    </div>
                  </Card>
                ))}
                {cards.length === 0 && (
                  <p className="text-xs text-muted-foreground py-4 text-center">Empty</p>
                )}
              </div>
            </Card>
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
      />
    </div>
  );
}
