import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, Pencil, RefreshCw, Send, Trash2, X } from "lucide-react";
import { api } from "@/api/client";
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
import { fetchAllApprovals, fetchAllInvoices } from "@/lib/invoices";
import { approveAndProcess, watchProcessingUntilIdle } from "@/lib/invoiceActions";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { cn } from "@/lib/cn";

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

function columnForInvoice(inv: Invoice): ColumnKey {
  if (inv.status === "rejected" || inv.status === "duplicate_skipped") return "rejected";
  if (inv.status === "processed") return "approved";
  if (inv.status === "exception") return "pending";
  if (PIPELINE_STATUSES.has(inv.status)) return "awaiting";
  return "pending";
}

function docNumber(inv: Invoice): string {
  return inv.invoice_no ?? `DOC-${String(inv.id).padStart(4, "0")}`;
}

async function fetchBoardInvoices(fresh: boolean): Promise<Invoice[]> {
  const [approvals, allInvoices] = await Promise.all([
    fetchAllApprovals(fresh),
    fetchAllInvoices(fresh),
  ]);
  const pipeline = allInvoices.filter((inv) => PIPELINE_STATUSES.has(inv.status));
  const approved = allInvoices.filter((inv) => inv.status === "processed");
  return mergeBoardInvoices(approvals, [...pipeline, ...approved]);
}

function mergeBoardInvoices(approvals: Invoice[], pipeline: Invoice[]): Invoice[] {
  const byId = new Map<number, Invoice>();
  for (const inv of pipeline) byId.set(inv.id, inv);
  for (const inv of approvals) byId.set(inv.id, inv);
  return [...byId.values()];
}

export function ApprovalsPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [drawerInvoice, setDrawerInvoice] = useState<Invoice | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEditMode, setDrawerEditMode] = useState(false);

  function openDrawer(inv: Invoice, edit = false) {
    setDrawerInvoice(inv);
    setDrawerEditMode(edit);
    setDrawerOpen(true);
  }
  const [busyId, setBusyId] = useState<number | null>(null);
  const [processingBusy, setProcessingBusy] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

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

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    const fresh = options?.fresh ?? !options?.silent;

    const boardResult = await Promise.allSettled([fetchBoardInvoices(fresh)]);

    if (boardResult[0].status === "fulfilled") {
      setInvoices(boardResult[0].value);
      if (!options?.silent) setError(null);
    } else if (!options?.silent) {
      setInvoices([]);
      const reason = boardResult[0].reason;
      setError(
        reason instanceof Error
          ? reason.message + API_HINT
          : "Failed to load approvals" + API_HINT
      );
    }

    if (!options?.silent) setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useVisibilityPolling(() => {
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
      cols[columnForInvoice(inv)].push(inv);
    }
    return cols;
  }, [invoices, searchQuery]);

  const queueCount = useMemo(
    () => invoices.filter((inv) => APPROVAL_QUEUE_STATUSES.has(inv.status)).length,
    [invoices]
  );

  const approveInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv) return;
    if (!inv.has_stored_file) {
      setToast("Upload a PDF before approving this invoice.");
      return;
    }
    setBusyId(id);
    try {
      setToast("Invoice queued for processing…");
      await approveAndProcess(id, () => load({ silent: true, fresh: true }));
      setToast("Invoice approved — processing complete");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  };

  const rejectInvoice = async (id: number) => {
    const inv = invoices.find((i) => i.id === id);
    if (!inv || (inv.status !== "exception" && inv.status !== "processed")) {
      setToast("This invoice cannot be rejected.");
      return;
    }
    setBusyId(id);
    try {
      await api.reject(id);
      setToast("Invoice rejected — file moved to rejected storage");
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Reject failed");
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
    if (inv.status !== "processed") {
      setToast("Publish is available for processed invoices only.");
      return;
    }
    if (inv.published_to_ledger) {
      setToast(`${documentDisplayRef(inv)} is already published.`);
      return;
    }
    setBusyId(inv.id);
    try {
      await api.publishInvoice(inv.id);
      setToast(`Published · ${documentDisplayRef(inv)}`);
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Publish failed");
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

  if (!loading && queueCount === 0 && board.awaiting.length === 0 && board.approved.length === 0) {
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
                            disabled={busyId === inv.id}
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
                            disabled={busyId === inv.id}
                            onClick={() => void rejectInvoice(inv.id)}
                            data-testid={`reject-${inv.id}`}
                          >
                            <X className="h-3 w-3 mr-0.5" />
                            Reject
                          </Button>
                        )}
                        {col.key === "approved" && !inv.published_to_ledger && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-1.5 text-[11px] text-primary"
                            onClick={() => void publish(inv)}
                            data-testid={`publish-${inv.id}`}
                          >
                            <Send className="h-3 w-3 mr-0.5" />
                            Publish
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
        }}
        startInEditMode={drawerEditMode}
        onUpdated={() => load({ fresh: true })}
      />
    </div>
  );
}
