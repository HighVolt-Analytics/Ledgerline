import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { FolderArchive } from "lucide-react";
import type { MatrixRow } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ListSearchInput } from "@/components/ListSearchInput";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { InboxSourceBadge } from "@/components/inbox/InboxSourceBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CapturedDocumentsSkeleton } from "@/components/skeleton/PageSkeletons";
import { CounterpartyColumnHeaderLink } from "@/components/upload/CounterpartyCreationsLink";
import {
  ActionCell,
  NatureBadge,
  PaymentStatusPill,
  PipelineStatusBadge,
  TypeBadge,
} from "@/components/upload/allDocumentsTablePills";
import {
  UploadCellClip,
  UploadCellText,
  UploadSummaryColGroup,
} from "@/components/upload/UploadCellText";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { useRuleBookDocumentTypes } from "@/hooks/useRuleBookConfig";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { UPLOAD_POLL_FAST_MS, UPLOAD_POLL_MS } from "@/lib/uploadPolling";
import {
  allDocumentsActionIssues,
  approvalStatusLabel,
  documentNature,
  formatDocDate,
  paymentStatusForNature,
  postingStatusLabel,
  toMatrixFlagType,
  toMatrixPaymentStatus,
  vaultCellValue,
} from "@/lib/allDocumentsSummary";
import { documentDisplayRef, money } from "@/lib/format";
import { counterpartyName, glPostingApplicable, invoiceSourceKind, invoiceSourceLabel } from "@/lib/invoice";
import {
  fetchMatrixPage,
  sortMatrixRowsNewestFirst,
  stagesToCells,
} from "@/lib/matrixApi";
import { isInvoicePipelineActive } from "@/lib/uploadColumnState";
import {
  API_PORT_HINT,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import type { UploadApprovalBoardCounts } from "@/lib/uploadApprovalFilter";

const InvoiceDetailDrawer = lazy(() =>
  import("@/components/InvoiceDetailDrawer").then((m) => ({
    default: m.InvoiceDetailDrawer,
  }))
);

export function AllDocumentsSummaryTable({
  onFlaggedCount,
  onDocumentCount,
  onGoUpload,
  refreshRef,
  searchQuery: controlledSearch,
  onSearchChange,
  captureSource,
  showUploadSource = true,
  title = "All documents",
  emptyTitle = "No documents yet",
  emptyHint = "Upload files or capture documents from Email, WhatsApp, or Viber.",
  approvalBoardColumns = [],
  onBoardCounts,
}: {
  onFlaggedCount?: (count: number) => void;
  onDocumentCount?: (count: number) => void;
  onGoUpload?: () => void;
  refreshRef?: MutableRefObject<(() => void) | null>;
  searchQuery?: string;
  onSearchChange?: (value: string) => void;
  /** When set, only documents from this ingest channel. */
  captureSource?: "upload" | "email" | "whatsapp" | "viber";
  /** Hide on per-channel tabs (source is already implied). */
  showUploadSource?: boolean;
  title?: string;
  emptyTitle?: string;
  emptyHint?: string;
  approvalBoardColumns?: Array<"review" | "processing" | "approved" | "rejected">;
  onBoardCounts?: (counts: UploadApprovalBoardCounts) => void;
}) {
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const { data: documentTypes } = useRuleBookDocumentTypes();
  const loadSeq = useRef(0);
  const loadInFlightRef = useRef(false);
  const [matrixData, setMatrixData] = useState<MatrixRow[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [filteredTotal, setFilteredTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [localSearch, setLocalSearch] = useState("");
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const searchQuery = controlledSearch ?? localSearch;
  const setSearchQuery = onSearchChange ?? setLocalSearch;
  const debouncedSearch = useDebouncedValue(searchQuery.trim());

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setMatrixData([]);
    setPage(1);
    setError(null);
    setDrawerInvoiceId(null);
    setDrawerOpen(false);
    setLoading(true);
  });

  function openInvoiceDrawer(invoiceId: number) {
    setDrawerInvoiceId(invoiceId);
    setDrawerOpen(true);
  }

  const matrixQueryParams = useMemo(() => {
    const params: Record<string, string> = {};
    if (captureSource) params.capture_source = captureSource;
    if (debouncedSearch) params.q = debouncedSearch;
    if (approvalBoardColumns.length > 0) {
      params.approval_board_column = approvalBoardColumns.join(",");
    }
    return params;
  }, [captureSource, debouncedSearch, approvalBoardColumns]);

  const load = useCallback(
    async (options?: { silent?: boolean; fresh?: boolean }) => {
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
        const result = await fetchMatrixPage(page, matrixQueryParams, fresh);
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setMatrixData(result.rows);
        setTotalPages(result.pages);
        setFilteredTotal(result.total);
        onFlaggedCount?.(result.summary.flagged);
        onDocumentCount?.(result.total);
        onBoardCounts?.(result.boardCounts);
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
          setError(e instanceof Error ? e.message : "Failed to load documents");
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
    },
    [tenantScope, page, matrixQueryParams, onFlaggedCount, onDocumentCount, onBoardCounts]
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, captureSource, approvalBoardColumns]);

  useEffect(() => {
    if (!refreshRef) return;
    refreshRef.current = () => {
      void load({ fresh: true });
    };
    return () => {
      refreshRef.current = null;
    };
  }, [load, refreshRef]);

  const rows = useMemo(() => sortMatrixRowsNewestFirst(matrixData), [matrixData]);

  const hasActiveProcessing = useMemo(
    () => rows.some((row) => isInvoicePipelineActive(row.invoice)),
    [rows]
  );

  useVisibilityPolling(() => {
    void load({ silent: true });
  }, hasActiveProcessing ? UPLOAD_POLL_FAST_MS : UPLOAD_POLL_MS, !loading && !error);

  if (error && rows.length === 0 && !loading) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {formatTenantLoadError(error, API_PORT_HINT)}
        <div className="mt-3">
          <Button variant="outline" size="sm" onClick={() => void load({ fresh: true })}>
            Retry
          </Button>
        </div>
      </Card>
    );
  }

  if (loading && rows.length === 0) {
    return <CapturedDocumentsSkeleton rows={8} />;
  }

  if (!loading && rows.length === 0) {
    return (
      <EmptyState
        title={emptyTitle}
        hint={emptyHint}
        action={
          onGoUpload ? (
            <Button size="sm" onClick={onGoUpload}>
              Upload files
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <>
      <Card className="overflow-hidden" data-testid="all-documents-summary-table">
        <div className="flex flex-col gap-3 px-3 sm:px-4 py-3 border-b border-border sm:flex-row sm:items-center sm:justify-between">
          <h3 className="text-sm font-semibold shrink-0">
            {title}
            <span className="text-muted-foreground tnum font-normal ml-2">
              ({filteredTotal})
            </span>
          </h3>
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search documents…"
            testId="input-all-documents-search"
            className="w-full sm:max-w-xs sm:ml-auto"
          />
        </div>

        <div className="overflow-x-auto">
          <table className={`all-docs-pills all-docs-table w-full text-sm font-normal ${showUploadSource ? "all-docs-table--summary-source" : "all-docs-table--summary"}`}>
            <UploadSummaryColGroup showSource={showUploadSource} />
            <thead>
              <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                <th className="px-3 py-1.5 font-medium" title="Document">Document</th>
                {showUploadSource ? (
                  <th className="px-3 py-1.5 font-medium" title="Upload source">Upload source</th>
                ) : null}
                <th className="px-3 py-1.5 font-medium" title="Type">Type</th>
                <th className="px-3 py-1.5 font-medium" title="Counterparty">
                  <CounterpartyColumnHeaderLink label="Counterparty" />
                </th>
                <th className="px-3 py-1.5 font-medium" title="Nature">Nature</th>
                <th className="px-3 py-1.5 font-medium" title="Doc date">Doc date</th>
                <th className="px-3 py-1.5 font-medium" title="Ledger">Ledger</th>
                <th className="px-3 py-1.5 font-medium" title="Amount">Amount</th>
                <th className="px-3 py-1.5 font-medium" title="Approval">Approval</th>
                <th className="px-3 py-1.5 font-medium" title="Posting">Posting</th>
                <th className="px-3 py-1.5 font-medium" title="Payment">Payment</th>
                <th className="px-3 py-1.5 font-medium" title="Action">Action</th>
                <th className="px-3 py-1.5 font-medium" title="Vault">Vault</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const inv = row.invoice;
                const docRef = documentDisplayRef(inv);
                const cells = stagesToCells(row.stages);
                const flag = toMatrixFlagType(row.flag);
                const payment = toMatrixPaymentStatus(row.payment_status);
                const nature = documentNature(inv, documentTypes);
                const action = allDocumentsActionIssues({
                  inv,
                  flag,
                  flagReason: row.flag_reason,
                  cells,
                  payment,
                  nature,
                  documentTypes,
                });
                const vault = vaultCellValue(inv);
                const approval = approvalStatusLabel(inv, cells, documentTypes, nature);
                const posting = postingStatusLabel(inv, cells, documentTypes, nature);
                const pay = paymentStatusForNature(payment, nature);

                return (
                  <tr
                    key={inv.id}
                    className="border-b border-border last:border-0 hover:bg-muted/40 cursor-pointer"
                    role="button"
                    tabIndex={0}
                    onClick={() => openInvoiceDrawer(inv.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        openInvoiceDrawer(inv.id);
                      }
                    }}
                    data-testid={`all-docs-row-${docRef}`}
                  >
                    <td className="px-3 py-2">
                      <UploadCellText value={docRef} className="tnum" />
                      {inv.invoice_no ? (
                        <UploadCellText
                          value={inv.invoice_no}
                          className="text-xs text-muted-foreground tnum"
                        />
                      ) : null}
                    </td>
                    {showUploadSource ? (
                      <td className="px-3 py-2">
                        <UploadCellClip title={invoiceSourceLabel(invoiceSourceKind(inv))}>
                          <InboxSourceBadge kind={invoiceSourceKind(inv)} />
                        </UploadCellClip>
                      </td>
                    ) : null}
                    <td className="px-3 py-2">
                      <UploadCellClip>
                        <TypeBadge inv={inv} documentTypes={documentTypes} />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellText value={counterpartyName(inv)} className="font-medium" />
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellClip title={nature ?? undefined}>
                        <NatureBadge nature={nature} />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellText value={formatDocDate(inv.invoice_date)} className="tnum text-xs" />
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellClip title={inv.account_name}>
                        <InboxGlAccountBadge
                          account={inv.account_name}
                          glPostingApplicable={glPostingApplicable(inv, documentTypes)}
                        />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellText value={money(inv.total, inv.currency)} className="tnum font-normal" />
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellClip title={approval}>
                        <PipelineStatusBadge label={approval} />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellClip title={posting}>
                        <PipelineStatusBadge label={posting} />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <UploadCellClip title={pay}>
                        <PaymentStatusPill status={pay} />
                      </UploadCellClip>
                    </td>
                    <td className="px-3 py-2">
                      <ActionCell
                        primary={action.primary}
                        all={action.all}
                        testId={`all-docs-action-${docRef}`}
                      />
                    </td>
                    <td className="px-3 py-2">
                      {vault.kind === "empty" ? (
                        <span className="text-muted-foreground text-xs">—</span>
                      ) : (
                        <span
                          className={
                            vault.kind === "vaulted"
                              ? "inline-flex items-center gap-1 text-xs min-w-0 max-w-full text-muted-foreground"
                              : "inline-flex items-center gap-1 text-xs min-w-0 max-w-full text-foreground"
                          }
                          title={
                            vault.kind === "po"
                              ? `PO bundle: ${vault.label}`
                              : vault.kind === "so"
                                ? `SO bundle: ${vault.label}`
                                : vault.label
                          }
                        >
                          <FolderArchive className="h-3.5 w-3.5 shrink-0" aria-hidden />
                          <span className="all-docs-clip">{vault.label}</span>
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {totalPages > 1 ? (
          <div className="flex items-center justify-between gap-3 px-3 sm:px-4 py-3 border-t border-border text-xs text-muted-foreground">
            <span className="tnum">
              Page {page} of {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </Card>

      {drawerInvoiceId != null ? (
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
      ) : null}
    </>
  );
}
