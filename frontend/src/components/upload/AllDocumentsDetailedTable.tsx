import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import type { Invoice, MatrixRow } from "@/api/types";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { ListSearchInput } from "@/components/ListSearchInput";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { InboxSourceBadge } from "@/components/inbox/InboxSourceBadge";
import { TableCirclePagination } from "@/components/purchases/ListPaginationFooter";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CapturedDocumentsSkeleton } from "@/components/skeleton/PageSkeletons";
import {
  CounterpartyColumnHeaderLink,
  UploadColumnCellLink,
  UploadColumnHeaderLink,
} from "@/components/upload/CounterpartyCreationsLink";
import {
  DuplicatePossibleBadge,
  NatureBadge,
  PaymentStatusPill,
  PipelineStatusBadge,
  RouteText,
  TableStatusTag,
  TypeBadge,
  authSyncStatusTone,
} from "@/components/upload/allDocumentsTablePills";
import {
  UPLOAD_DETAILED_TABLE_WIDTH_REM,
  UPLOAD_DETAILED_TABLE_WIDTH_WITH_SOURCE_REM,
  UploadCellClip,
  UploadCellText,
  UploadDetailedColGroup,
} from "@/components/upload/UploadCellText";
import { UploadColumnCell, UploadColumnProcessingIndicator } from "@/components/upload/UploadColumnCell";
import { UploadDocumentRowActions } from "@/components/upload/UploadDocumentRowActions";
import { InvoiceIssueHintIcon } from "@/components/inbox/InvoiceIssueHintIcon";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { useLatestRef } from "@/hooks/useLatestRef";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { useRuleBookDocumentTypes } from "@/hooks/useRuleBookConfig";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { UPLOAD_POLL_FAST_MS, UPLOAD_POLL_MS } from "@/lib/uploadPolling";
import { duplicateCellValue, normalizeAuthSyncLabel } from "@/lib/allDocumentsDetailed";
import {
  documentNature,
  formatDocDate,
  formatUploadedAt,
  postingStatusLabel,
  toMatrixPaymentStatus,
} from "@/lib/allDocumentsSummary";
import { documentDisplayRef, money } from "@/lib/format";
import { counterpartyName, glPostingApplicable, invoiceSourceKind, invoiceSourceLabel } from "@/lib/invoice";
import { approveAndProcess } from "@/lib/invoiceActions";
import type { DocumentRowDrawerTab } from "@/lib/documentRowActions";
import type { InvoiceDrawerTab } from "@/components/InvoiceDetailDrawer";
import {
  fetchMatrixPage,
  sortMatrixRowsNewestFirst,
  stagesToCells,
} from "@/lib/matrixApi";
import {
  derivedColumnProcessingMode,
  isInvoicePipelineActive,
  uploadColumnDisplayMode,
  valueOrProcessingMode,
} from "@/lib/uploadColumnState";
import {
  API_PORT_HINT,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import type { UploadApprovalBoardCounts } from "@/lib/uploadApprovalFilter";
import { EMPTY_UPLOAD_APPROVAL_FILTER } from "@/lib/uploadApprovalFilter";
import { queryKeys } from "@/lib/queryClient";
import { useQueryClient } from "@tanstack/react-query";

const InvoiceDetailDrawer = lazy(() =>
  import("@/components/InvoiceDetailDrawer").then((m) => ({
    default: m.InvoiceDetailDrawer,
  }))
);

function AuthSyncBadge({
  label,
  testId,
}: {
  label?: string | null;
  testId?: string;
  quietPending?: boolean;
}) {
  const normalized = normalizeAuthSyncLabel(label);
  if (normalized === "—") {
    return (
      <span className="text-muted-foreground text-xs" data-testid={testId}>
        —
      </span>
    );
  }
  return (
    <TableStatusTag tone={authSyncStatusTone(normalized)} title={normalized} testId={testId}>
      {normalized}
    </TableStatusTag>
  );
}

function summaryPipelineModes(
  inv: MatrixRow["invoice"],
  documentTypes: Parameters<typeof documentNature>[1],
  processingIds: ReadonlySet<number>,
  nature: ReturnType<typeof documentNature>
) {
  const opts = { processingIds, documentTypes };
  return {
    active: isInvoicePipelineActive(inv, processingIds),
    type: uploadColumnDisplayMode(inv, "documentType", opts),
    route: uploadColumnDisplayMode(inv, "route", opts),
    nature: valueOrProcessingMode(Boolean(nature), inv, processingIds),
    invoiceNo: uploadColumnDisplayMode(inv, "documentMeta", opts),
    counterparty: uploadColumnDisplayMode(inv, "counterparty", opts),
    invoiceDate: valueOrProcessingMode(Boolean(inv.invoice_date?.trim()), inv, processingIds),
    dueDate: valueOrProcessingMode(Boolean(inv.due_date?.trim()), inv, processingIds),
    total: uploadColumnDisplayMode(inv, "total", opts),
    ledger: uploadColumnDisplayMode(inv, "glAccount", opts),
    derived: derivedColumnProcessingMode(inv, processingIds),
  };
}

export function AllDocumentsDetailedTable({
  onFlaggedCount,
  onDocumentCount,
  onGoUpload,
  refreshRef,
  searchQuery: controlledSearch,
  onSearchChange,
  captureSource,
  routeTarget,
  showUploadSource = true,
  showSearchHeader = true,
  emptyTitle = "No documents yet",
  emptyHint = "Upload files or capture documents from Email, WhatsApp, or Viber.",
  approvalBoardColumns = EMPTY_UPLOAD_APPROVAL_FILTER,
  onBoardCounts,
}: {
  onFlaggedCount?: (count: number) => void;
  onDocumentCount?: (count: number) => void;
  onGoUpload?: () => void;
  refreshRef?: MutableRefObject<(() => void) | null>;
  searchQuery?: string;
  onSearchChange?: (value: string) => void;
  captureSource?: "upload" | "email" | "whatsapp" | "viber" | "slack";
  /** Exact Invoice.route_target (e.g. "Team Expenses"). Omits filter when unset. */
  routeTarget?: string;
  showUploadSource?: boolean;
  showSearchHeader?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  approvalBoardColumns?: Array<"review" | "processing" | "approved" | "rejected">;
  onBoardCounts?: (counts: UploadApprovalBoardCounts) => void;
}) {
  const { user } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const tenantScope = user?.tenant_id ?? null;
  const { data: documentTypes } = useRuleBookDocumentTypes();
  const loadSeq = useRef(0);
  const loadInFlightRef = useRef(false);
  const [matrixData, setMatrixData] = useState<MatrixRow[]>([]);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [localSearch, setLocalSearch] = useState("");
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerInitialTab, setDrawerInitialTab] = useState<InvoiceDrawerTab>("fields");
  const [processingIds, setProcessingIds] = useState<Set<number>>(() => new Set());
  const [busyActionId, setBusyActionId] = useState<number | null>(null);

  const searchQuery = controlledSearch ?? localSearch;
  const setSearchQuery = onSearchChange ?? setLocalSearch;
  const debouncedSearch = useDebouncedValue(searchQuery.trim());
  const approvalBoardKey = approvalBoardColumns.join(",");
  const onFlaggedCountRef = useLatestRef(onFlaggedCount);
  const onDocumentCountRef = useLatestRef(onDocumentCount);
  const onBoardCountsRef = useLatestRef(onBoardCounts);
  const quietAuthPending =
    captureSource === "email" || captureSource === "whatsapp" || captureSource === "viber" || captureSource === "slack";

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setMatrixData([]);
    setPage(1);
    setTotalCount(0);
    setError(null);
    setDrawerInvoiceId(null);
    setDrawerOpen(false);
    setDrawerInitialTab("fields");
    setProcessingIds(new Set());
    setBusyActionId(null);
    setLoading(true);
  });

  function openInvoiceDrawer(invoiceId: number, tab: DocumentRowDrawerTab | InvoiceDrawerTab = "fields") {
    setDrawerInitialTab(tab === "po" ? "po" : "fields");
    setDrawerInvoiceId(invoiceId);
    setDrawerOpen(true);
  }

  const matrixQueryParams = useMemo(() => {
    const params: Record<string, string> = {};
    if (captureSource) params.capture_source = captureSource;
    if (routeTarget) params.route_target = routeTarget;
    if (debouncedSearch) params.q = debouncedSearch;
    if (approvalBoardKey) {
      params.approval_board_column = approvalBoardKey;
    }
    return params;
  }, [captureSource, routeTarget, debouncedSearch, approvalBoardKey]);

  const load = useCallback(
    async (options?: { silent?: boolean; fresh?: boolean }) => {
      if (options?.silent && loadInFlightRef.current && !options.fresh) return null;
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
        setTotalCount(result.total);
        onFlaggedCountRef.current?.(result.summary.flagged);
        onDocumentCountRef.current?.(result.total);
        onBoardCountsRef.current?.(result.boardCounts);
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
    [tenantScope, page, matrixQueryParams]
  );

  const refreshAfterRowAction = useCallback(async () => {
    await load({ silent: true, fresh: true });
    void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
  }, [load, queryClient]);

  async function handleRowApprove(inv: Invoice) {
    setBusyActionId(inv.id);
    setProcessingIds((prev) => new Set(prev).add(inv.id));
    try {
      await approveAndProcess(inv.id, refreshAfterRowAction);
      toast({ title: "Approved" });
    } catch (e) {
      toast({
        title: e instanceof Error ? e.message : "Approve failed",
        variant: "destructive",
      });
    } finally {
      setBusyActionId(null);
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(inv.id);
        return next;
      });
    }
  }

  async function handleRowReject(inv: Invoice) {
    if (!window.confirm(`Reject ${inv.vendor ?? documentDisplayRef(inv)}?`)) return;
    setBusyActionId(inv.id);
    try {
      await api.reject(inv.id);
      await refreshAfterRowAction();
      toast({ title: "Rejected" });
    } catch (e) {
      toast({
        title: e instanceof Error ? e.message : "Reject failed",
        variant: "destructive",
      });
    } finally {
      setBusyActionId(null);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, captureSource, routeTarget, approvalBoardKey]);

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
    () =>
      processingIds.size > 0 ||
      rows.some((row) => isInvoicePipelineActive(row.invoice, processingIds)),
    [rows, processingIds]
  );

  useVisibilityPolling(
    () => load({ silent: true }),
    hasActiveProcessing ? UPLOAD_POLL_FAST_MS : UPLOAD_POLL_MS,
    !loading && !error
  );

  if (error && rows.length === 0 && !loading) {
    return (
      <Card className="all-docs-table-card p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
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
        className="all-docs-table-card"
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
      <Card className="all-docs-table-card overflow-hidden" data-testid="all-documents-summary-table">
        {showSearchHeader ? (
          <div className="flex items-center px-3 sm:px-4 py-3 border-b border-border">
            <ListSearchInput
              value={searchQuery}
              onChange={setSearchQuery}
              placeholder="Search documents…"
              testId="input-all-documents-summary-search"
              className="w-full sm:max-w-[14.5rem]"
            />
          </div>
        ) : null}

        <div className="all-docs-table-card__mobile all-docs-pills md:hidden divide-y divide-border">
          {rows.map((matrixRow) => {
            const inv = matrixRow.invoice;
            const docRef = documentDisplayRef(inv);
            const dup = duplicateCellValue(matrixRow);
            const nature = documentNature(inv, documentTypes);
            const cells = stagesToCells(matrixRow.stages);
            const posting = postingStatusLabel(inv, cells, documentTypes, nature);
            const modes = summaryPipelineModes(inv, documentTypes, processingIds, nature);
            return (
              <button
                key={inv.id}
                type="button"
                className="w-full text-left px-3 py-3 hover:bg-muted/40"
                onClick={() => openInvoiceDrawer(inv.id)}
                data-testid={`all-docs-summary-mobile-${docRef}`}
              >
                <div className="flex items-start justify-between gap-3 min-w-0">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium tnum inline-flex items-center gap-1.5 min-w-0 max-w-full">
                      {modes.active ? <UploadColumnProcessingIndicator /> : null}
                      <span className="truncate">{docRef}</span>
                    </div>
                    <div className="mt-1">
                      <UploadColumnCell mode={modes.type}>
                        <TypeBadge inv={inv} documentTypes={documentTypes} />
                      </UploadColumnCell>
                    </div>
                    <div className="text-sm all-docs-clip mt-0.5" title={counterpartyName(inv)}>
                      <UploadColumnCell mode={modes.counterparty}>
                        {counterpartyName(inv)}
                      </UploadColumnCell>
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1 tnum">
                      <UploadColumnCell mode={modes.invoiceDate}>
                        {formatDocDate(inv.invoice_date)}
                        {inv.due_date ? ` · due ${formatDocDate(inv.due_date)}` : ""}
                        {` · uploaded ${formatUploadedAt(inv.created_at)}`}
                      </UploadColumnCell>
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1 flex flex-wrap gap-2">
                      {showUploadSource ? (
                        <InboxSourceBadge kind={invoiceSourceKind(inv)} />
                      ) : null}
                      {dup.kind === "possible" ? (
                        <span className="text-[#b05374] dark:text-[#e7b6c3]">
                          Dup: {dup.label}
                        </span>
                      ) : dup.kind === "conflict" ? (
                        <span>Dup: {dup.label}</span>
                      ) : null}
                    </div>
                  </div>
                  <div className="shrink-0 tnum font-normal text-sm">
                    <UploadColumnCell mode={modes.total} align="right">
                      {money(inv.total, inv.currency)}
                    </UploadColumnCell>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 mt-2">
                  <UploadColumnCell mode={modes.route}>
                    <RouteText inv={inv} documentTypes={documentTypes} />
                  </UploadColumnCell>
                  <UploadColumnCell mode={modes.nature}>
                    <NatureBadge nature={nature} />
                  </UploadColumnCell>
                  <UploadColumnCell mode={modes.ledger}>
                    <InboxGlAccountBadge
                      account={inv.account_name}
                      glPostingApplicable={glPostingApplicable(inv, documentTypes)}
                    />
                  </UploadColumnCell>
                  <UploadColumnCell mode={modes.derived}>
                    <PipelineStatusBadge label={posting} />
                  </UploadColumnCell>
                  <UploadColumnCell mode={modes.derived}>
                    <AuthSyncBadge label={matrixRow.acc_sync} quietPending={quietAuthPending} />
                  </UploadColumnCell>
                  <span
                    className="ml-auto"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <UploadDocumentRowActions
                      inv={inv}
                      documentTypes={documentTypes}
                      busy={busyActionId === inv.id}
                      pipelineActive={modes.active}
                      iconOnly
                      onOpenDrawer={(tab) => openInvoiceDrawer(inv.id, tab ?? "fields")}
                      onApprove={() => void handleRowApprove(inv)}
                      onReject={() => void handleRowReject(inv)}
                    />
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="all-docs-table-card__scroll hidden md:block">
          <table
            className="all-docs-pills all-docs-table-fixed text-sm"
            style={{
              tableLayout: "fixed",
              width: `${showUploadSource ? UPLOAD_DETAILED_TABLE_WIDTH_WITH_SOURCE_REM : UPLOAD_DETAILED_TABLE_WIDTH_REM}rem`,
            }}
          >
            <UploadDetailedColGroup showSource={showUploadSource} />
            <thead>
              <tr className="border-b border-border bg-muted/30 text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium" title="Document">Document</th>
                {showUploadSource ? (
                  <th className="px-3 py-2 font-medium" title="Upload source">Upload source</th>
                ) : null}
                <th className="px-3 py-2 font-medium" title="Duplicate">Duplicate</th>
                <th className="px-3 py-2 font-medium" title="Type">Type</th>
                <th className="px-3 py-2 font-medium" title="Route">Route</th>
                <th className="px-3 py-2 font-medium" title="Nature">Nature</th>
                <th className="px-3 py-2 font-medium" title="Invoice no.">Invoice no.</th>
                <th className="px-3 py-2 font-medium" title="Counterparty">
                  <CounterpartyColumnHeaderLink label="Counterparty" />
                </th>
                <th className="px-3 py-2 font-medium" title="Invoice date">Invoice date</th>
                <th className="px-3 py-2 font-medium" title="Due date">Due date</th>
                <th className="px-3 py-2 font-medium" title="Currency + amount">Currency + amount</th>
                <th className="px-3 py-2 font-medium" title="Ledger">Ledger</th>
                <th className="px-3 py-2 font-medium" title="Advance Auth">
                  <UploadColumnHeaderLink
                    label="Advance Auth"
                    to="/team-expenses"
                    hint="Click to go to Team Expenses"
                    testId="matrix-advance-auth-header-link"
                  />
                </th>
                <th className="px-3 py-2 font-medium" title="Budget auth">
                  <UploadColumnHeaderLink
                    label="Budget auth"
                    to="/team-expenses"
                    hint="Click to go to Team Expenses"
                    testId="matrix-budget-auth-header-link"
                  />
                </th>
                <th className="px-3 py-2 font-medium" title="Posting">Posting</th>
                <th className="px-3 py-2 font-medium" title="Payment auth">
                  <UploadColumnHeaderLink
                    label="Payment auth"
                    to="/payments"
                    hint="Click to go to Payments"
                    testId="matrix-payment-auth-header-link"
                  />
                </th>
                <th className="px-3 py-2 font-medium" title="Acc sync">Acc sync</th>
                <th className="px-3 py-2 font-medium" title="When this document was uploaded">Uploaded</th>
                <th className="px-3 py-2 font-medium" title="Actions">Actions</th>
                <th
                  className="px-2 py-2 font-medium text-center w-10"
                  title="Issue details — hover for how to resolve"
                >
                  i
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((matrixRow) => {
                const inv = matrixRow.invoice;
                const docRef = documentDisplayRef(inv);
                const dup = duplicateCellValue(matrixRow);
                const nature = documentNature(inv, documentTypes);
                const cells = stagesToCells(matrixRow.stages);
                const posting = postingStatusLabel(inv, cells, documentTypes, nature);
                const payment = toMatrixPaymentStatus(matrixRow.payment_status);
                const modes = summaryPipelineModes(inv, documentTypes, processingIds, nature);

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
                    data-testid={`all-docs-summary-row-${docRef}`}
                  >
                    <td className="px-3 py-2.5">
                      <span className="inline-flex items-center gap-1.5 min-w-0 max-w-full">
                        {modes.active ? <UploadColumnProcessingIndicator /> : null}
                        <UploadCellText value={docRef} className="font-medium tnum" />
                      </span>
                    </td>
                    {showUploadSource ? (
                      <td className="px-3 py-2.5">
                        <UploadCellClip title={invoiceSourceLabel(invoiceSourceKind(inv))}>
                          <InboxSourceBadge kind={invoiceSourceKind(inv)} />
                        </UploadCellClip>
                      </td>
                    ) : null}
                    <td className="px-3 py-2.5">
                      {dup.kind === "empty" ? (
                        <span className="text-muted-foreground text-xs">—</span>
                      ) : dup.kind === "possible" ? (
                        <UploadCellClip title={dup.label}>
                          <DuplicatePossibleBadge label={dup.label} />
                        </UploadCellClip>
                      ) : (
                        <UploadCellText value={dup.label} className="tnum text-xs font-medium" />
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.type}>
                        <UploadCellClip>
                          <TypeBadge inv={inv} documentTypes={documentTypes} />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.route}>
                        <UploadCellClip>
                          <RouteText inv={inv} documentTypes={documentTypes} />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.nature}>
                        <UploadCellClip title={nature ?? undefined}>
                          <NatureBadge nature={nature} />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.invoiceNo}>
                        <UploadCellText value={inv.invoice_no?.trim() || "—"} className="tnum text-xs" />
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.counterparty}>
                        <UploadCellText value={counterpartyName(inv)} />
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.invoiceDate}>
                        <UploadCellText value={formatDocDate(inv.invoice_date)} className="tnum text-xs" />
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.dueDate}>
                        <UploadCellText value={formatDocDate(inv.due_date)} className="tnum text-xs" />
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.total}>
                        <UploadCellText value={money(inv.total, inv.currency)} className="tnum font-normal" />
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.ledger}>
                        <UploadCellClip title={inv.account_name}>
                          <InboxGlAccountBadge
                            account={inv.account_name}
                            glPostingApplicable={glPostingApplicable(inv, documentTypes)}
                          />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.derived}>
                        <UploadColumnCellLink
                          to="/team-expenses"
                          hint="Open Team Expenses"
                          testId="matrix-advance-auth-cell-link"
                        >
                          <UploadCellClip title={normalizeAuthSyncLabel(matrixRow.advance_auth)}>
                            <AuthSyncBadge label={matrixRow.advance_auth} />
                          </UploadCellClip>
                        </UploadColumnCellLink>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.derived}>
                        <UploadColumnCellLink
                          to="/team-expenses"
                          hint="Open Team Expenses"
                          testId="matrix-budget-auth-cell-link"
                        >
                          <UploadCellClip title={normalizeAuthSyncLabel(matrixRow.budget_auth)}>
                            <AuthSyncBadge label={matrixRow.budget_auth} />
                          </UploadCellClip>
                        </UploadColumnCellLink>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.derived}>
                        <UploadCellClip title={posting}>
                          <PipelineStatusBadge label={posting} />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.derived}>
                        <UploadColumnCellLink
                          to="/payments"
                          hint="Open Payments"
                          testId="matrix-payment-auth-cell-link"
                        >
                          <UploadCellClip title={payment}>
                            <PaymentStatusPill status={payment} />
                          </UploadCellClip>
                        </UploadColumnCellLink>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadColumnCell mode={modes.derived}>
                        <UploadCellClip title={normalizeAuthSyncLabel(matrixRow.acc_sync)}>
                          <AuthSyncBadge
                            label={matrixRow.acc_sync}
                            quietPending={quietAuthPending}
                          />
                        </UploadCellClip>
                      </UploadColumnCell>
                    </td>
                    <td className="px-3 py-2.5">
                      <UploadCellText
                        value={formatUploadedAt(inv.created_at)}
                        className="tnum text-xs"
                      />
                    </td>
                    <td
                      className="all-docs-actions-cell px-3 py-2.5"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <UploadDocumentRowActions
                        inv={inv}
                        documentTypes={documentTypes}
                        busy={busyActionId === inv.id}
                        pipelineActive={modes.active}
                        onOpenDrawer={(tab) => openInvoiceDrawer(inv.id, tab ?? "fields")}
                        onApprove={() => void handleRowApprove(inv)}
                        onReject={() => void handleRowReject(inv)}
                      />
                    </td>
                    <td
                      className="px-2 py-2.5 text-center"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <InvoiceIssueHintIcon
                        inv={inv}
                        cells={cells}
                        flagReason={matrixRow.flag_reason}
                        testId={`all-docs-issue-${docRef}`}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <TableCirclePagination
          page={page}
          totalPages={totalPages}
          total={totalCount}
          onPageChange={setPage}
        />
      </Card>

      {drawerInvoiceId != null ? (
        <Suspense fallback={null}>
          <InvoiceDetailDrawer
            invoiceId={drawerInvoiceId}
            open={drawerOpen}
            initialTab={drawerInitialTab}
            onClose={() => {
              setDrawerOpen(false);
              setDrawerInvoiceId(null);
              setDrawerInitialTab("fields");
            }}
            onUpdated={() => void load({ silent: true, fresh: true })}
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
        </Suspense>
      ) : null}
    </>
  );
}
