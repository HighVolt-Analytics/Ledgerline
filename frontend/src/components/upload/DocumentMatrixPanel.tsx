import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, Check, Clock, Minus, RefreshCw } from "lucide-react";
import type { Invoice, MatrixRow } from "@/api/types";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { MatrixFlagBadge } from "@/components/matrix/MatrixFlagBadge";
import { MatrixFlagDrawer } from "@/components/matrix/MatrixFlagDrawer";
import { MatrixPaymentBadge } from "@/components/matrix/MatrixPaymentBadge";
import { MatrixStageCell } from "@/components/matrix/MatrixStageCell";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Card } from "@/components/ui/card";
import { documentDisplayRef, money } from "@/lib/format";
import { counterpartyColumnLabel, counterpartyName, invoiceMatchesCaptureChannel } from "@/lib/invoice";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import { invoiceDocumentTypeDisplayLabel } from "@/lib/documentTypeResolve";
import { CounterpartyColumnHeaderLink } from "@/components/upload/CounterpartyCreationsLink";
import { MATRIX_STAGES, matrixStageSettled, type MatrixCellState, type MatrixStage } from "@/lib/matrix";
import { fetchAllMatrixRows, sortMatrixRowsNewestFirst, stagesToCells } from "@/lib/matrixApi";
import type { MatrixFlagType, MatrixPaymentStatus } from "@/lib/v4MatrixMockData";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { cn } from "@/lib/cn";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { approveAndProcess, validateInvoiceReadyForApproval } from "@/lib/invoiceActions";
import { isInvoicePipelineActive } from "@/lib/uploadColumnState";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { queryKeys, tenantQueryKey } from "@/lib/queryClient";
import {
  API_PORT_HINT,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

const InvoiceDetailDrawer = lazy(() =>
  import("@/components/InvoiceDetailDrawer").then((m) => ({
    default: m.InvoiceDetailDrawer,
  }))
);

const MATRIX_POLL_MS = 15_000;
const MATRIX_POLL_FAST_MS = 4_000;
const PAGE_SIZE = 10;

const QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

type MatrixFilter = "all" | "anomalies" | "awaiting" | "paid" | "pending" | "failed";

const FILTER_PILLS: { key: MatrixFilter; label: string }[] = [
  { key: "all", label: "Show all" },
  { key: "anomalies", label: "Anomalies only" },
  { key: "pending", label: "Pending" },
  { key: "failed", label: "Failed" },
  { key: "awaiting", label: "Awaiting payment" },
  { key: "paid", label: "Paid this month" },
];

type MatrixTableRow = {
  inv: Invoice;
  cells: ReturnType<typeof stagesToCells>;
  flag: MatrixFlagType;
  payment: MatrixPaymentStatus;
  paidDate?: string | null;
  reason?: string;
  conflictWith?: string;
  conflictDetail?: import("@/lib/v4MatrixMockData").MatrixConflictRow[];
};

function isPaidThisMonth(paidDate: string | null | undefined): boolean {
  if (!paidDate) return false;
  const paid = new Date(paidDate);
  if (Number.isNaN(paid.getTime())) return false;
  const now = new Date();
  return paid.getFullYear() === now.getFullYear() && paid.getMonth() === now.getMonth();
}

function stageBlocked(flag: MatrixFlagType, cellState: MatrixCellState | undefined): boolean {
  return flag !== "Clean" && cellState === "pending";
}

function rowHasPendingStage(row: MatrixTableRow): boolean {
  return MATRIX_STAGES.some((stage) => row.cells[stage as MatrixStage]?.state === "pending");
}

function rowHasFailedStage(row: MatrixTableRow): boolean {
  return MATRIX_STAGES.some((stage) => {
    const cell = row.cells[stage as MatrixStage];
    if (cell?.state === "fail") return true;
    return (
      (stage === "Approved" || stage === "Posted") &&
      stageBlocked(row.flag, cell?.state)
    );
  });
}

function toFlagType(value: string): MatrixFlagType {
  if (value === "Anomaly Detected") return "Anomaly Detected";
  if (value === "Duplicate Suspected") return "Duplicate Suspected";
  if (value === "Quarantined") return "Quarantined";
  return "Clean";
}

function toPaymentStatus(value: string): MatrixPaymentStatus {
  const allowed: MatrixPaymentStatus[] = [
    "Paid",
    "Awaiting Payment",
    "Payment Approved",
    "On Hold",
    "Failed",
    "—",
  ];
  return allowed.includes(value as MatrixPaymentStatus) ? (value as MatrixPaymentStatus) : "—";
}

function rowFromApi(row: MatrixRow): MatrixTableRow {
  const flag = toFlagType(row.flag);
  return {
    inv: row.invoice,
    cells: stagesToCells(row.stages),
    flag,
    payment: toPaymentStatus(row.payment_status),
    paidDate: row.paid_date ?? null,
    reason: row.flag_reason ?? undefined,
    conflictWith: row.conflict_with ?? undefined,
    conflictDetail: row.conflict_detail?.map((line) => ({
      field: line.field,
      thisDoc: line.this_doc,
      otherDoc: line.other_doc,
    })),
  };
}

function matrixDocumentTypeChip(
  inv: Invoice,
  documentTypes?: DocumentTypeDefinition[] | null
) {
  const code = (inv.document_type_code ?? "").trim();
  const typeLabel = invoiceDocumentTypeDisplayLabel(inv, documentTypes);
  return (
    <DocumentTypeChip
      code={code}
      label={typeLabel}
      display={typeLabel}
      title={typeLabel}
      purchaseKind={inv.purchase_document_type}
      documentTypes={documentTypes}
    />
  );
}

export function DocumentMatrixPanel({
  embedded = false,
  showKpis = true,
  showControls = true,
  showTable = true,
  showLegend = true,
  captureSource,
  onFlaggedCount,
  onGoUpload,
  refreshRef,
}: {
  embedded?: boolean;
  showKpis?: boolean;
  showControls?: boolean;
  showTable?: boolean;
  showLegend?: boolean;
  /** When set, only show documents for this Upload channel tab. */
  captureSource?: "upload" | "email" | "whatsapp" | "viber";
  onFlaggedCount?: (count: number) => void;
  onGoUpload?: () => void;
  refreshRef?: MutableRefObject<(() => void) | null>;
}) {
  const { user } = useAuth();
  const { data: ruleBook } = useRuleBookConfig();
  const documentTypes = ruleBook?.documentTypes;
  const queryClient = useQueryClient();

  const invalidateManagementCaches = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.purchases() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.purchasesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sales() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.salesTwoWay() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() }),
      queryClient.invalidateQueries({ queryKey: tenantQueryKey(["invoices"]) }),
    ]);
  }, [queryClient]);
  const tenantScope = user?.tenant_id ?? null;
  const loadSeq = useRef(0);
  const loadInFlightRef = useRef(false);
  const [matrixData, setMatrixData] = useState<MatrixRow[]>([]);
  const [filter, setFilter] = useState<MatrixFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [flagDrawerId, setFlagDrawerId] = useState<number | null>(null);
  const [resolveBusy, setResolveBusy] = useState(false);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setMatrixData([]);
    setPage(1);
    setError(null);
    setFlagDrawerId(null);
    setDrawerInvoiceId(null);
    setDrawerOpen(false);
    setLoading(true);
  });

  function openInvoiceDrawer(invoiceId: number) {
    setDrawerInvoiceId(invoiceId);
    setDrawerOpen(true);
  }

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (options?.silent && loadInFlightRef.current) return null;
    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    } else {
      loadInFlightRef.current = true;
    }
    const fresh = options?.fresh ?? !options?.silent;
    try {
      const data = await fetchAllMatrixRows(fresh);
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setMatrixData(data);
    } catch (e) {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      if (
        handleTenantScopedLoadFailure(e, {
          retry: () => {
            void load({ silent: true, fresh: true });
          },
        })
      ) {
        return;
      }
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load document matrix");
        setMatrixData([]);
      }
    } finally {
      if (options?.silent) {
        loadInFlightRef.current = false;
      }
      if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope) && !options?.silent) {
        setLoading(false);
      }
    }
  }, [tenantScope]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!refreshRef) return;
    refreshRef.current = () => {
      void load({ fresh: true });
    };
    return () => {
      refreshRef.current = null;
    };
  }, [load, refreshRef]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const matrixRows = useMemo<MatrixTableRow[]>(() => {
    const scoped = captureSource
      ? matrixData.filter((row) => invoiceMatchesCaptureChannel(row.invoice, captureSource))
      : matrixData;
    return sortMatrixRowsNewestFirst(scoped).map(rowFromApi);
  }, [matrixData, captureSource]);

  useEffect(() => {
    setPage(1);
  }, [captureSource]);

  const hasActiveProcessing = useMemo(
    () => matrixRows.some((row) => isInvoicePipelineActive(row.inv)),
    [matrixRows]
  );

  const matrixPollMs = hasActiveProcessing ? MATRIX_POLL_FAST_MS : MATRIX_POLL_MS;

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: hasActiveProcessing });
  }, matrixPollMs);

  const filteredRows = useMemo(
    () =>
      matrixRows.filter((row) => {
        if (!invoiceMatchesListSearch(row.inv, searchQuery)) return false;
        if (filter === "anomalies") {
          return (
            row.flag === "Anomaly Detected" ||
            row.flag === "Duplicate Suspected" ||
            row.flag === "Quarantined"
          );
        }
        if (filter === "awaiting") {
          return row.payment === "Awaiting Payment" || row.payment === "Payment Approved";
        }
        if (filter === "paid") {
          return row.payment === "Paid" && isPaidThisMonth(row.paidDate);
        }
        if (filter === "pending") {
          return rowHasPendingStage(row);
        }
        if (filter === "failed") {
          return rowHasFailedStage(row);
        }
        return true;
      }),
    [matrixRows, filter, searchQuery]
  );

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  const pagedRows = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [filteredRows, page]);

  useEffect(() => {
    setPage(1);
  }, [filter, searchQuery]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const kpis = useMemo(
    () => ({
      flagged: matrixRows.filter((r) => r.flag !== "Clean").length,
      duplicates: matrixRows.filter((r) => r.flag === "Duplicate Suspected").length,
      awaiting: matrixRows.filter(
        (r) => r.payment === "Awaiting Payment" || r.payment === "Payment Approved"
      ).length,
      paid: matrixRows.filter(
        (r) => r.payment === "Paid" && isPaidThisMonth(r.paidDate)
      ).length,
    }),
    [matrixRows]
  );

  useEffect(() => {
    onFlaggedCount?.(kpis.flagged);
  }, [kpis.flagged, onFlaggedCount]);

  const flagDrawerRow = useMemo(
    () => matrixRows.find((r) => r.inv.id === flagDrawerId) ?? null,
    [matrixRows, flagDrawerId]
  );

  async function resolveFlag(inv: Invoice, action: "unique" | "duplicate" | "approval") {
    setResolveBusy(true);
    try {
      if (action === "unique") {
        if (QUEUE_STATUSES.has(inv.status)) {
          if (!inv.has_stored_file) {
            setToast("Upload a document file before approving.");
            return;
          }
          const fieldCheck = validateInvoiceReadyForApproval(inv, ruleBook?.documentTypes);
          if (!fieldCheck.ok) {
            setToast(fieldCheck.message);
            return;
          }
          await approveAndProcess(inv.id, async () => {
            await load({ silent: true, fresh: true });
          });
          setToast(`${documentDisplayRef(inv)} approved and processed`);
        } else {
          setToast(`${documentDisplayRef(inv)} — open the document to resolve routing or mapping`);
          setFlagDrawerId(null);
          openInvoiceDrawer(inv.id);
        }
      } else if (action === "duplicate") {
        if (inv.status === "duplicate_skipped" || inv.status === "rejected") {
          await api.deleteApprovalPermanently(inv.id);
          setToast(`${documentDisplayRef(inv)} permanently removed`);
        } else {
          await api.reject(inv.id);
          setToast(`${documentDisplayRef(inv)} rejected as duplicate`);
        }
        await invalidateManagementCaches();
      } else {
        await api.requestApproval(inv.id);
        setToast(`${documentDisplayRef(inv)} sent to approvals`);
      }
      setFlagDrawerId(null);
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Could not update document");
    } finally {
      setResolveBusy(false);
    }
  }

  if (error) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {formatTenantLoadError(error, API_PORT_HINT)}
      </Card>
    );
  }

  return (
    <div>
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {toast}
        </div>
      )}

      {!embedded && (
        <div className="flex justify-end mb-4">
          <Button
            variant="surface"
            size="sm"
            onClick={() => load({ fresh: true })}
            disabled={loading}
            data-testid="button-matrix-refresh"
          >
            <RefreshCw className={cn("h-4 w-4 mr-1", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      )}

      {loading && matrixData.length === 0 ? (
        <TableSkeleton rows={6} columns={5} />
      ) : matrixRows.length === 0 && showTable ? (
        <EmptyState
          title={
            captureSource === "email"
              ? "No email documents in the matrix"
              : captureSource === "whatsapp"
                ? "No WhatsApp documents in the matrix"
                : captureSource === "viber"
                  ? "No Viber documents in the matrix"
                  : captureSource === "upload"
                    ? "No upload documents in the matrix"
                    : "No documents in the matrix"
          }
          hint={
            captureSource && captureSource !== "upload"
              ? "Documents captured on this channel will appear here."
              : "Connect a mailbox and fetch documents, or upload an invoice."
          }
          action={
            onGoUpload ? (
              <Button onClick={onGoUpload} data-testid="button-matrix-go-upload">
                {captureSource && captureSource !== "upload" ? "View detailed list" : "Go to Upload"}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {showKpis ? (
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
              <KpiCard label="Documents" value={matrixRows.length} testid="kpi-matrix-docs" />
              <KpiCard
                label="Flagged for review"
                value={kpis.flagged}
                testid="kpi-matrix-flagged"
                delta={
                  kpis.flagged > 0
                    ? { dir: "up", text: `${kpis.duplicates} duplicates`, good: false }
                    : undefined
                }
              />
              <KpiCard
                label="Awaiting payment"
                value={kpis.awaiting}
                testid="kpi-matrix-awaiting"
              />
              <KpiCard label="Paid this month" value={kpis.paid} testid="kpi-matrix-paid" />
            </div>
          ) : null}

          {showControls ? (
            <div className="flex items-center gap-2 mb-3 w-full">
              <ListSearchInput
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search this list…"
                testId="input-matrix-search"
                className="w-[760px] shrink-0"
              />
              <div className="flex items-center gap-2 flex-nowrap overflow-x-auto whitespace-nowrap pr-1">
                {FILTER_PILLS.map((pill) => (
                  <button
                    key={pill.key}
                    type="button"
                    onClick={() => setFilter(pill.key)}
                    data-testid={`matrix-filter-${pill.key}`}
                    className={cn(
                      "rounded-full px-3 py-1 text-xs font-medium border transition-colors shrink-0",
                      filter === pill.key
                        ? "bg-primary text-primary-foreground border-primary"
                        : "border-border text-muted-foreground hover:text-foreground hover-elevate"
                    )}
                  >
                    {pill.label}
                  </button>
                ))}
              </div>
              <span className="text-xs text-muted-foreground shrink-0 hidden sm:inline ml-auto">
                {filteredRows.length} of {matrixRows.length} documents
                {filteredRows.length > PAGE_SIZE ? ` · page ${page} of ${totalPages}` : ""}
              </span>
            </div>
          ) : null}

          {showTable ? <Card className="overflow-hidden">
            <div className="md:hidden divide-y divide-border">
              {pagedRows.length === 0 && (
                <div className="matrix-table-empty text-sm">
                  No documents match your search.
                </div>
              )}
              {pagedRows.map(({ inv, cells, flag, payment }) => {
                const docRef = documentDisplayRef(inv);
                const flagged = flag !== "Clean";
                const completedStages = MATRIX_STAGES.filter((stage) =>
                  matrixStageSettled(cells[stage as MatrixStage]?.state ?? "pending")
                ).length;
                return (
                  <div
                    key={inv.id}
                    className="px-3 py-3 cursor-pointer hover:bg-muted/40"
                    role="button"
                    tabIndex={0}
                    onClick={() => openInvoiceDrawer(inv.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openInvoiceDrawer(inv.id);
                      }
                    }}
                    data-testid={`matrix-row-${docRef}`}
                  >
                    <div className="flex items-start justify-between gap-3 min-w-0">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium tnum">{docRef}</div>
                        <div className="mt-1">{matrixDocumentTypeChip(inv, documentTypes)}</div>
                        <div className="text-xs text-muted-foreground truncate mt-1">
                          {inv.invoice_no ?? "—"} · {counterpartyName(inv)}
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          {completedStages}/{MATRIX_STAGES.length} stages complete
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="tnum font-medium text-sm">
                          {money(inv.total, inv.currency)}
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 mt-2">
                      {flagged ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFlagDrawerId(inv.id);
                          }}
                          data-testid={`matrix-flag-${docRef}`}
                          className="text-left"
                        >
                          <MatrixFlagBadge flag={flag} />
                        </button>
                      ) : (
                        <MatrixFlagBadge flag={flag} />
                      )}
                      <MatrixPaymentBadge status={payment} />
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-border">
                    <th className="px-4 py-2.5 text-left font-medium sticky left-0 bg-card z-10">
                      Document
                    </th>
                    <th className="px-3 py-2.5 text-left font-medium whitespace-nowrap">Type</th>
                    <th className="px-3 py-2.5 text-left font-medium">
                      <CounterpartyColumnHeaderLink
                        label={counterpartyColumnLabel({ mixed: true })}
                      />
                    </th>
                    {MATRIX_STAGES.map((stage) => (
                      <th key={stage} className="px-3 py-2.5 text-center font-medium">
                        {stage}
                      </th>
                    ))}
                    <th className="px-3 py-2.5 text-left font-medium border-l border-border">
                      Anomaly / Duplicate
                    </th>
                    <th className="px-3 py-2.5 text-left font-medium">Payment Status</th>
                    <th className="px-4 py-2.5 text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedRows.length === 0 && (
                    <tr>
                      <td
                        colSpan={MATRIX_STAGES.length + 6}
                        className="matrix-table-empty text-sm"
                      >
                        No documents match your search.
                      </td>
                    </tr>
                  )}
                  {pagedRows.map(({ inv, cells, flag, payment }) => {
                    const docRef = documentDisplayRef(inv);
                    const flagged = flag !== "Clean";
                    return (
                      <tr
                        key={inv.id}
                        className="row-band border-b border-border/60 last:border-0 cursor-pointer hover:bg-muted/30"
                        onClick={() => openInvoiceDrawer(inv.id)}
                        data-testid={`matrix-row-${docRef}`}
                      >
                        <td className="px-4 py-2 sticky left-0 bg-card z-10">
                          <div className="font-medium tnum">{docRef}</div>
                          <div className="text-xs text-muted-foreground tnum">
                            {inv.invoice_no ?? "—"}
                          </div>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {matrixDocumentTypeChip(inv, documentTypes)}
                        </td>
                        <td className="px-3 py-2 max-w-[150px] truncate text-muted-foreground">
                          {counterpartyName(inv)}
                        </td>
                        {MATRIX_STAGES.map((stage) => {
                          const cell = cells[stage as MatrixStage];
                          const blocked =
                            (stage === "Approved" || stage === "Posted") &&
                            stageBlocked(flag, cell?.state);
                          return (
                            <td key={stage} className="px-3 py-2 text-center">
                              <MatrixStageCell
                                stage={stage as MatrixStage}
                                cell={cell}
                                blocked={blocked}
                                flag={flag}
                              />
                            </td>
                          );
                        })}
                        <td className="px-3 py-2 border-l border-border">
                          {flagged ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setFlagDrawerId(inv.id);
                              }}
                              data-testid={`matrix-flag-${docRef}`}
                              className="text-left"
                            >
                              <MatrixFlagBadge flag={flag} />
                            </button>
                          ) : (
                            <MatrixFlagBadge flag={flag} />
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <MatrixPaymentBadge status={payment} />
                        </td>
                        <td className="px-4 py-2 text-right tnum font-medium">
                          {money(inv.total, inv.currency)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-between gap-3 px-3 sm:px-4 py-3 border-t border-border">
                <p className="text-xs text-muted-foreground">
                  Page {page} of {totalPages}
                </p>
                <div className="flex items-center gap-1.5">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-xs"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    Prev
                  </Button>
                  <div className="hidden sm:flex items-center gap-1.5">
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                    <Button
                      key={p}
                      variant={p === page ? "default" : "outline"}
                      size="sm"
                      className="h-8 min-w-8 px-2 text-xs tnum"
                      onClick={() => setPage(p)}
                    >
                      {p}
                    </Button>
                  ))}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-xs"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </Card> : null}

          {showLegend ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <StatusPill className={pillTones.ok}>
                <Check className="matrix-ok-icon h-3 w-3 shrink-0" />
                Complete
              </StatusPill>
              <StatusPill className={pillTones.muted}>
                <Clock className="h-3 w-3" />
                Pending
              </StatusPill>
              <StatusPill className={pillTones.bad}>
                <Ban className="h-3 w-3" />
                Failed / blocked
              </StatusPill>
              <StatusPill className={pillTones.muted}>
                <Minus className="h-3 w-3" />
                Skipped (not applicable)
              </StatusPill>
              <StatusPill className={pillTones.amber}>
                <AlertTriangle className="h-3 w-3 ds-warning-icon" />
                Anomaly routes through approval before payment
              </StatusPill>
            </div>
          ) : null}
        </>
      )}

      {showTable ? (
        <>
          <MatrixFlagDrawer
            row={
              flagDrawerRow
                ? {
                    inv: flagDrawerRow.inv,
                    flag: flagDrawerRow.flag,
                    reason: flagDrawerRow.reason,
                    conflictWith: flagDrawerRow.conflictWith,
                    conflictDetail: flagDrawerRow.conflictDetail,
                    cells: flagDrawerRow.cells,
                  }
                : null
            }
            open={flagDrawerId !== null}
            onClose={() => setFlagDrawerId(null)}
            busy={resolveBusy}
            onResolve={(_docId, action) => {
              const inv = flagDrawerRow?.inv;
              if (inv) void resolveFlag(inv, action);
            }}
          />

          <Suspense fallback={null}>
            <InvoiceDetailDrawer
              invoiceId={drawerInvoiceId}
              open={drawerOpen}
              onClose={() => {
                setDrawerOpen(false);
                setDrawerInvoiceId(null);
              }}
              onUpdated={() => void load({ silent: true, fresh: true })}
            />
          </Suspense>
        </>
      ) : null}
    </div>
  );
}
