import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { FolderArchive } from "lucide-react";
import type { MatrixRow } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ListSearchInput } from "@/components/ListSearchInput";
import { VisionHeadingBadge } from "@/components/inbox/DocumentTypeDisplay";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { InboxSourceBadge } from "@/components/inbox/InboxSourceBadge";
import { MatrixPaymentBadge } from "@/components/matrix/MatrixPaymentBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CapturedDocumentsSkeleton } from "@/components/skeleton/PageSkeletons";
import { StatusPill, pillTones } from "@/components/StatusPill";
import { CounterpartyColumnHeaderLink } from "@/components/upload/CounterpartyCreationsLink";
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
  type PipelineStatusLabel,
} from "@/lib/allDocumentsSummary";
import { cn } from "@/lib/cn";
import { KLASS_NON_TRANSACTIONAL, KLASS_TRANSACTIONAL } from "@/lib/documentTypeKlass";
import { documentDisplayRef, money } from "@/lib/format";
import { counterpartyName, glPostingApplicable, invoiceSourceKind } from "@/lib/invoice";
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

const InvoiceDetailDrawer = lazy(() =>
  import("@/components/InvoiceDetailDrawer").then((m) => ({
    default: m.InvoiceDetailDrawer,
  }))
);

function NatureBadge({ nature }: { nature: ReturnType<typeof documentNature> }) {
  if (!nature) return <span className="text-muted-foreground text-xs">—</span>;
  const transactional = nature === KLASS_TRANSACTIONAL;
  return (
    <StatusPill
      className={
        transactional
          ? "border-primary/30 bg-primary/10 text-primary"
          : pillTones.muted
      }
    >
      {nature === KLASS_NON_TRANSACTIONAL ? "Non-transactional" : "Transactional"}
    </StatusPill>
  );
}

function PipelineStatusBadge({ label }: { label: PipelineStatusLabel }) {
  if (label === "Done" || label === "Posted") {
    return <StatusPill className={pillTones.ok}>{label}</StatusPill>;
  }
  if (label === "Failed") {
    return <StatusPill className={pillTones.bad}>{label}</StatusPill>;
  }
  if (label === "Pending") {
    return <StatusPill className={pillTones.amber}>{label}</StatusPill>;
  }
  return <span className="text-muted-foreground text-xs">{label}</span>;
}

function ActionCell({
  primary,
  all,
  testId,
}: {
  primary: { label: string; detail?: string } | null;
  all: { label: string; detail?: string }[];
  testId?: string;
}) {
  if (!primary) {
    return (
      <span className="text-muted-foreground text-xs" data-testid={testId}>
        —
      </span>
    );
  }
  const title = all
    .map((issue) => (issue.detail ? `${issue.label}: ${issue.detail}` : issue.label))
    .join("\n");
  return (
    <span title={title} data-testid={testId} className="inline-flex max-w-full">
      <StatusPill className={pillTones.amber}>
        <span className="truncate max-w-[10rem]">{primary.label}</span>
      </StatusPill>
    </span>
  );
}

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
}) {
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const { data: documentTypes } = useRuleBookDocumentTypes();
  const loadSeq = useRef(0);
  const loadInFlightRef = useRef(false);
  const [matrixData, setMatrixData] = useState<MatrixRow[]>([]);
  const [flagged, setFlagged] = useState(0);
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
    return params;
  }, [captureSource, debouncedSearch]);

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
        setFlagged(result.summary.flagged);
        onFlaggedCount?.(result.summary.flagged);
        onDocumentCount?.(result.total);
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
    [tenantScope, page, matrixQueryParams, onFlaggedCount, onDocumentCount]
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, captureSource]);

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
              ({filteredTotal}
              {flagged > 0 ? ` · ${flagged} flagged` : ""})
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
          <table className={cn("w-full text-sm", showUploadSource ? "min-w-[72rem]" : "min-w-[66rem]")}>
            <thead>
              <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">Document</th>
                {showUploadSource ? (
                  <th className="px-3 py-2 font-medium">Upload source</th>
                ) : null}
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">
                  <CounterpartyColumnHeaderLink label="Counterparty" />
                </th>
                <th className="px-3 py-2 font-medium">Nature</th>
                <th className="px-3 py-2 font-medium">Doc date</th>
                <th className="px-3 py-2 font-medium">Ledger</th>
                <th className="px-3 py-2 font-medium text-right">Amount</th>
                <th className="px-3 py-2 font-medium">Approval</th>
                <th className="px-3 py-2 font-medium">Posting</th>
                <th className="px-3 py-2 font-medium">Payment</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">Vault</th>
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
                    <td className="px-3 py-2.5 align-top min-w-[8rem]">
                      <div className="font-medium tnum">{docRef}</div>
                      {inv.invoice_no ? (
                        <div className="text-xs text-muted-foreground truncate tnum">
                          {inv.invoice_no}
                        </div>
                      ) : null}
                    </td>
                    {showUploadSource ? (
                      <td className="px-3 py-2.5 align-top">
                        <InboxSourceBadge kind={invoiceSourceKind(inv)} />
                      </td>
                    ) : null}
                    <td className="px-3 py-2.5 align-top max-w-[10rem]">
                      <VisionHeadingBadge inv={inv} empty="" />
                    </td>
                    <td className="px-3 py-2.5 align-top max-w-[10rem]">
                      <span className="truncate block">{counterpartyName(inv)}</span>
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <NatureBadge nature={nature} />
                    </td>
                    <td className="px-3 py-2.5 align-top tnum text-xs whitespace-nowrap">
                      {formatDocDate(inv.invoice_date)}
                    </td>
                    <td className="px-3 py-2.5 align-top max-w-[9rem]">
                      <InboxGlAccountBadge
                        account={inv.account_name}
                        glPostingApplicable={glPostingApplicable(inv, documentTypes)}
                      />
                    </td>
                    <td className="px-3 py-2.5 align-top text-right tnum whitespace-nowrap font-medium">
                      {money(inv.total, inv.currency)}
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <PipelineStatusBadge label={approval} />
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <PipelineStatusBadge label={posting} />
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <MatrixPaymentBadge status={pay} />
                    </td>
                    <td className="px-3 py-2.5 align-top max-w-[11rem]">
                      <ActionCell
                        primary={action.primary}
                        all={action.all}
                        testId={`all-docs-action-${docRef}`}
                      />
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      {vault.kind === "empty" ? (
                        <span className="text-muted-foreground text-xs">—</span>
                      ) : (
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-xs",
                            vault.kind === "vaulted"
                              ? "text-muted-foreground"
                              : "text-foreground"
                          )}
                          title={
                            vault.kind === "po"
                              ? `PO bundle: ${vault.label}`
                              : vault.kind === "so"
                                ? `SO bundle: ${vault.label}`
                                : "Stored in vault"
                          }
                        >
                          <FolderArchive className="h-3.5 w-3.5 shrink-0" aria-hidden />
                          <span className="truncate max-w-[7rem]">{vault.label}</span>
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
