import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { CloudUpload, Mail, Plus, RefreshCw } from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, Invoice, MailboxBackfillJob } from "@/api/types";
import { ConnectMailboxDialog } from "@/components/ConnectMailboxDialog";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { useMailboxes } from "@/hooks/useMailboxes";
import {
  API_PORT_HINT,
  canRenderTenantOwnedUi,
  formatTenantLoadError,
} from "@/lib/tenantSession";
import { ListSearchInput } from "@/components/ListSearchInput";
import { MailboxImportDialog } from "@/components/mailboxes/MailboxImportDialog";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { PageTabs } from "@/components/PageTabs";
import { DocumentMatrixPanel } from "@/components/upload/DocumentMatrixPanel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Select } from "@/components/ui/select";
import {
  counterpartyColumnLabel,
  counterpartyMatchColumnLabel,
  isNeedsReviewEvaluation,
  mailboxDisplayName,
} from "@/lib/invoice";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { sortInvoicesNewestFirst } from "@/lib/invoices";
import { useNavBadges } from "@/hooks/useNavBadges";
import {
  invalidateUploadInvoiceList,
  useUploadInvoiceList,
} from "@/hooks/useUploadInvoiceList";
import {
  UploadEmailChannelPanel,
  UploadViberChannelPanel,
  UploadWhatsappChannelPanel,
} from "@/components/upload/UploadChannelPanels";
import {
  UploadInvoiceMobileRow,
  UploadInvoiceTableRow,
} from "@/components/upload/UploadInvoiceListRow";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryClient";
import { mergeBoardRowWithLocal, shouldClearProcessingId } from "@/lib/approvalsBoard";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import {
  BULK_UPLOAD_MAX_FILES,
  filterUploadFiles,
  formatBulkUploadNotice,
  type BulkUploadItemResult,
  UPLOAD_ACCEPT,
  uploadFilesInBatch,
  watchInvoiceIdsForVendorHold,
} from "@/lib/bulkUpload";
import { UploadDropZone } from "@/components/upload/UploadDropZone";

type ChannelTab = "upload" | "email" | "whatsapp" | "viber";
type ViewTab = "summary" | "detailed";

function parseChannelTab(value: string | null): ChannelTab {
  if (value === "upload" || value === "email" || value === "whatsapp" || value === "viber") {
    return value;
  }
  return "upload";
}

function parseViewTab(searchParams: URLSearchParams): ViewTab {
  if (searchParams.get("view") === "detailed" || searchParams.get("tab") === "detailed") {
    return "detailed";
  }
  return "summary";
}

const UPLOAD_LOAD_HINT =
  `${API_PORT_HINT.trim()} and migrations are up to date `;
const PROCESSING_WAIT_MS = 120_000;
const PAGE_SIZE = 10;
const NOTICE_AUTO_DISMISS_MS = 5000; // upload / mailbox notices (not in-progress fetch/import)

function isProgressNotice(notice: string): boolean {
  return (
    notice.startsWith("Fetch queued") ||
    notice.startsWith("Processing…") ||
    notice.startsWith("Historical import started")
  );
}

async function waitForProcessingIdle(timeoutMs = PROCESSING_WAIT_MS): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let sawRunning = false;
  while (Date.now() < deadline) {
    const status = await api.getProcessingStatus();
    if (status.state === "running" || status.active_tasks > 0) {
      sawRunning = true;
    }
    if (sawRunning && status.state === "idle" && status.active_tasks === 0) {
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function mailboxNickname(mb: ConnectedMailbox): string {
  const label = mb.display_name?.trim();
  if (label && !label.includes("@") && !label.includes("(")) {
    return label;
  }
  return mailboxDisplayName(mb.email, mb.display_name);
}

function isMailboxPollable(mb: ConnectedMailbox): boolean {
  return mb.is_active && mb.connection_status === "connected";
}

function uploadListRowSignature(inv: Invoice): string {
  return [
    inv.id,
    inv.status,
    inv.evaluation_status ?? "",
    inv.current_stage ?? "",
    inv.current_stage_state ?? "",
    inv.vendor ?? "",
    inv.total ?? "",
    inv.route_target ?? "",
    inv.validation_pass_rate ?? "",
    inv.vendor_confidence ?? "",
    inv.document_type_code ?? "",
    inv.account_name ?? "",
    inv.created_at,
  ].join("|");
}

function sameUploadListRows(prev: Invoice[], next: Invoice[]): boolean {
  if (prev.length !== next.length) return false;
  return prev.every((row, index) => uploadListRowSignature(row) === uploadListRowSignature(next[index]!));
}

export function UploadPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";
  const [searchParams, setSearchParams] = useSearchParams();
  const channelTab = parseChannelTab(searchParams.get("channel"));
  const viewTab = parseViewTab(searchParams);
  const { data: navBadges } = useNavBadges();
  const [matrixFlagged, setMatrixFlagged] = useState(0);
  const matrixRefreshRef = useRef<(() => void) | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const prevMergedRef = useRef<Invoice[]>([]);
  const { data: ruleBook } = useRuleBookConfig();
  const {
    data: mailboxQueryData = [],
    blocked: mailboxesBlocked,
    refetch: refetchMailboxes,
  } = useMailboxes(Boolean(user));
  const [source, setSource] = useState("all");
  const [evalFilter, setEvalFilter] = useState<"all" | "needs_review">("all");
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get("q") ?? "");
  const debouncedSearch = useDebouncedValue(searchQuery.trim());

  useEffect(() => {
    // Only sync when the URL explicitly carries q — do not wipe local typing when
    // other params (e.g. tab) change.
    if (!searchParams.has("q")) return;
    const q = searchParams.get("q") ?? "";
    setSearchQuery((current) => (current === q ? current : q));
  }, [searchParams]);
  const [addOpen, setAddOpen] = useState(false);
  const [fetching, setFetching] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ completed: number; total: number } | null>(
    null
  );
  const [fetchNotice, setFetchNotice] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importMailbox, setImportMailbox] = useState<ConnectedMailbox | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importJob, setImportJob] = useState<MailboxBackfillJob | null>(null);
  const [page, setPage] = useState(1);
  const [processingIds, setProcessingIds] = useState<Set<number>>(() => new Set());
  const tenantScope = user?.tenant_id ?? null;
  const mailboxes = canRenderTenantOwnedUi(tenantScope) && !mailboxesBlocked ? mailboxQueryData : [];

  const selectedMailboxId = useMemo(() => {
    if (source === "all") return null;
    return mailboxes.find((mb) => mb.email === source)?.id ?? null;
  }, [source, mailboxes]);

  const {
    data: listData,
    isLoading: listLoading,
    isError: listIsError,
    error: listError,
    refetch: refetchInvoiceList,
  } = useUploadInvoiceList({
    page,
    pageSize: PAGE_SIZE,
    source,
    q: debouncedSearch,
    mailboxId: selectedMailboxId,
    enabled:
      canRenderTenantOwnedUi(tenantScope) &&
      viewTab === "detailed" &&
      channelTab === "upload",
    processingIds,
  });

  const rawRows = listData?.rows ?? [];
  const all = useMemo(() => {
    const prevById = new Map(prevMergedRef.current.map((inv) => [inv.id, inv]));
    const merged = rawRows.map((row) =>
      mergeBoardRowWithLocal(row, prevById.get(row.id), processingIds)
    );
    const next =
      sameUploadListRows(prevMergedRef.current, merged) ? prevMergedRef.current : merged;
    prevMergedRef.current = next;
    return next;
  }, [rawRows, processingIds]);

  const totalInvoices = listData?.total ?? 0;
  const totalPages = listData?.pages ?? 1;
  const loading = listLoading && all.length === 0;
  const error =
    listIsError && listError instanceof Error ? listError.message : listIsError ? "Failed to load documents" : null;

  useLayoutEffect(() => {
    if (source !== "all" && !mailboxes.some((mb) => mb.email === source)) {
      setSource("all");
    }
  }, [tenantScope, mailboxes, source]);

  useResetOnTenantChange(() => {
    prevMergedRef.current = [];
    setPage(1);
    setSource("all");
    setDrawerId(null);
    setDrawerOpen(false);
    setImportMailbox(null);
    setImportJob(null);
    setFetchNotice(null);
    setProcessingIds(new Set());
  });

  useEffect(() => {
    setPage(1);
  }, [source, debouncedSearch]);

  // Clear merged rows only on page/source changes. Search keeps previous rows via
  // keepPreviousData so the list (and search input) do not unmount mid-keystroke.
  useEffect(() => {
    prevMergedRef.current = [];
  }, [page, source]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  useEffect(() => {
    if (!fetchNotice || isProgressNotice(fetchNotice)) return;
    const timer = window.setTimeout(() => setFetchNotice(null), NOTICE_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [fetchNotice]);

  const captured = useMemo(() => {
    if (!canRenderTenantOwnedUi(tenantScope)) return [];
    const rows = all.filter((r) => r.status !== "duplicate_skipped");
    return sortInvoicesNewestFirst(rows);
  }, [all, tenantScope]);

  const filtered = useMemo(() => {
    if (evalFilter === "needs_review") {
      return captured.filter((inv) => isNeedsReviewEvaluation(inv.evaluation_status));
    }
    return captured;
  }, [captured, evalFilter]);

  const hasActiveSearch = Boolean(searchQuery.trim() || debouncedSearch);
  // Keep the captured-documents chrome (incl. search) mounted while searching so
  // focus is not lost when the query key refetches or returns zero matches.
  const showCapturedChrome = captured.length > 0 || hasActiveSearch;

  useEffect(() => {
    setProcessingIds((prev) => {
      if (prev.size === 0) return prev;
      const byId = new Map(all.map((row) => [row.id, row]));
      let changed = false;
      const next = new Set(prev);
      for (const id of prev) {
        const row = byId.get(id);
        if (row && shouldClearProcessingId(row.status, true)) {
          next.delete(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [all]);

  const docsPerMailbox = useMemo(() => {
    const counts = new Map<number, number>();
    for (const inv of captured) {
      if (inv.connected_mailbox_id != null) {
        counts.set(
          inv.connected_mailbox_id,
          (counts.get(inv.connected_mailbox_id) ?? 0) + 1
        );
      }
    }
    return counts;
  }, [captured]);

  const openDrawer = (id: number) => {
    setDrawerId(id);
    setDrawerOpen(true);
  };

  const docsPerChannel = useMemo(() => {
    let whatsapp = 0;
    let viber = 0;
    for (const inv of captured) {
      const src = (inv.capture_source ?? "").toLowerCase();
      if (src.includes("whatsapp")) whatsapp += 1;
      if (src.includes("viber")) viber += 1;
    }
    return { whatsapp, viber };
  }, [captured]);

  const setChannelTab = (tab: ChannelTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "upload") next.delete("channel");
    else next.set("channel", tab);
    setSearchParams(next, { replace: true });
  };

  const setViewTab = (tab: ViewTab) => {
    const next = new URLSearchParams(searchParams);
    next.delete("tab");
    if (tab === "detailed") next.set("view", "detailed");
    else next.delete("view");
    setSearchParams(next, { replace: true });
  };

  const inboxCount = navBadges?.inbox_count ?? 0;

  async function sendMailboxInvite(body: {
    email: string;
    display_name?: string;
    message?: string;
  }) {
    const result = await api.createMailboxConnectionRequest(body);
    setFetchNotice(
      result.email_sent
        ? `Invitation sent to ${body.email}`
        : `Invitation created for ${body.email}. Copy the invite link from the dialog if email delivery failed.`
    );
    return result;
  }

  function applyMailboxUpdate(_updated: ConnectedMailbox) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes() });
  }

  async function toggleMailboxActive(mb: ConnectedMailbox) {
    setFetchNotice(null);
    try {
      const updated = await api.toggleMailbox(mb.id);
      applyMailboxUpdate(updated);
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Failed to update mailbox");
    }
  }

  async function removeMailbox(mb: ConnectedMailbox) {
    setFetchNotice(null);
    try {
      await api.removeMailbox(mb.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes() });
      if (source === mb.email) {
        setSource("all");
        setPage(1);
      }
      await invalidateUploadInvoiceList(queryClient);
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Failed to remove mailbox");
    }
  }

  async function fetchMailbox(mailbox: ConnectedMailbox) {
    if (!isMailboxPollable(mailbox)) {
      setFetchNotice(
        mailbox.last_error ||
          "Mailbox is not connected — send a reconnect invitation to restore fetch."
      );
      return;
    }
    setFetching(mailbox.email);
    setFetchNotice(null);
    const beforeTotal = totalInvoices;
    const beforeIds = new Set(all.map((i) => i.id));
    try {
      await api.triggerProcess(mailbox.id);
      setFetchNotice("Fetch queued — waiting for worker…");
      await waitForProcessingIdle();
      void refetchMailboxes();

      let latestTotal = beforeTotal;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        const result = await refetchInvoiceList();
        const snapshot = result.data;
        if (snapshot != null) latestTotal = snapshot.total;
        const hasNewDoc = snapshot?.rows.some((row) => !beforeIds.has(row.id)) ?? false;
        if (latestTotal > beforeTotal || hasNewDoc) {
          setPage(1);
          break;
        }
        if (attempt < 19) {
          setFetchNotice("Processing… checking for new documents");
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
      setFetchNotice(null);
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Fetch failed");
      void refetchMailboxes();
    } finally {
      setFetching(null);
    }
  }

  async function reconnectMailbox(mb: ConnectedMailbox) {
    setFetchNotice(null);
    try {
      const result = await api.createMailboxConnectionRequest({
        email: mb.email,
        display_name: mb.display_name ?? undefined,
        message: "Please reconnect your mailbox to restore invoice capture.",
      });
      setFetchNotice(
        result.email_sent
          ? `Reconnect invitation sent to ${mb.email}`
          : `Reconnect invitation created for ${mb.email}. Share the invite link from Integrations if email delivery failed.`
      );
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Failed to send reconnect invitation");
    }
  }

  async function startHistoricalImport(payload: {
    from_date: string;
    mark_processed: boolean;
  }) {
    if (!importMailbox) return;
    setImportBusy(true);
    setFetchNotice(null);
    try {
      const queued = await api.startMailboxBackfill(importMailbox.id, payload);
      const mailboxId = importMailbox.id;
      setImportJob(queued.job);
      setImportMailbox(null);
      setFetchNotice("Historical import started…");

      const deadline = Date.now() + PROCESSING_WAIT_MS;
      let job = queued.job;
      while (
        Date.now() < deadline &&
        (job.status === "queued" || job.status === "running")
      ) {
        await new Promise((r) => setTimeout(r, 2000));
        job = await api.getMailboxBackfillStatus(mailboxId, job.id, { fresh: true });
        setImportJob(job);
      }

      await waitForProcessingIdle();
      setPage(1);
      await invalidateUploadInvoiceList(queryClient);

      if (job.status === "completed") {
        setFetchNotice(
          `Import complete — ${job.attachments_ingested} attachment(s) ingested from ${job.messages_scanned} message(s).`
        );
      } else if (job.status === "failed") {
        setFetchNotice(job.error_message ?? "Historical import failed");
      } else {
        setFetchNotice("Import still running — refresh later for results.");
      }
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImportBusy(false);
    }
  }

  async function runUpload(rawFiles: File[]) {
    const { accepted, skipped } = filterUploadFiles(rawFiles);
    if (accepted.length === 0) {
      if (skipped > 0) {
        setFetchNotice(`${skipped} file(s) skipped — supported types: PDF, JPG, PNG, DOCX.`);
      }
      return;
    }

    const files =
      accepted.length > BULK_UPLOAD_MAX_FILES
        ? accepted.slice(0, BULK_UPLOAD_MAX_FILES)
        : accepted;
    const truncated = accepted.length > files.length;

    setUploading(true);
    setUploadFiles(files);
    setUploadProgress({ completed: 0, total: files.length });
    setFetchNotice(null);
    try {
      const summary = await uploadFilesInBatch(files, {
        onProgress: (completed, total) => setUploadProgress({ completed, total }),
      });
      let notice = formatBulkUploadNotice(summary);
      if (skipped > 0) {
        notice = `${skipped} unsupported file(s) skipped. ${notice}`;
      }
      if (truncated) {
        notice = `${notice} Only the first ${BULK_UPLOAD_MAX_FILES} files were uploaded.`;
      }
      setFetchNotice(notice);
      setPage(1);
      await invalidateUploadInvoiceList(queryClient);
      const uploadedIds = summary.results
        .filter((row): row is Extract<BulkUploadItemResult, { ok: true }> => row.ok)
        .flatMap((row) => row.invoiceIds);
      if (uploadedIds.length > 0) {
        setProcessingIds((prev) => {
          const next = new Set(prev);
          for (const id of uploadedIds) next.add(id);
          return next;
        });
        void (async () => {
          const holdNotice = await watchInvoiceIdsForVendorHold(uploadedIds, {
            onPoll: async () => {
              await refetchInvoiceList();
            },
          });
          if (holdNotice) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.pendingVendors() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
            setFetchNotice((prev) => (prev ? `${prev} ${holdNotice}` : holdNotice));
          }
        })();
        window.setTimeout(() => {
          void refetchInvoiceList();
        }, 3000);
      }
    } catch (err) {
      setFetchNotice(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setUploadFiles([]);
      setUploadProgress(null);
    }
  }

  async function uploadDocuments(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (selected.length === 0) return;
    await runUpload(selected);
  }

  const headerActions =
    channelTab === "email" && isAdmin ? (
      <Button data-testid="button-add-mailbox" onClick={() => setAddOpen(true)}>
        <Plus className="h-4 w-4 mr-1.5 shrink-0" />
        Add mailbox
      </Button>
    ) : channelTab === "upload" && viewTab === "summary" ? (
      <Button
        variant="surface"
        size="sm"
        data-testid="button-matrix-refresh"
        onClick={() => matrixRefreshRef.current?.()}
      >
        <RefreshCw className="h-4 w-4 mr-1" />
        Refresh
      </Button>
    ) : null;

  const workspaceShell = (content: ReactNode) => (
    <div>
      <PageHeader
        actions={headerActions}
        headline={
          <PageTabs
            value={channelTab}
            onChange={(value) => setChannelTab(value as ChannelTab)}
            data-testid="upload-channel-tabs"
            tabs={[
              {
                value: "upload",
                testid: "tab-upload-upload",
                label: (
                  <span className="inline-flex items-center gap-2">
                    <CloudUpload className="h-4 w-4 text-primary" />
                    Upload
                  </span>
                ),
              },
              {
                value: "email",
                testid: "tab-upload-email",
                label: (
                  <span className="inline-flex items-center gap-2">
                    <IntegrationBrandIcon id="graph" size={16} />
                    Email
                  </span>
                ),
              },
              {
                value: "whatsapp",
                testid: "tab-upload-whatsapp",
                label: (
                  <span className="inline-flex items-center gap-2">
                    <IntegrationBrandIcon id="whatsapp" size={16} />
                    WhatsApp
                  </span>
                ),
              },
              {
                value: "viber",
                testid: "tab-upload-viber",
                label: (
                  <span className="inline-flex items-center gap-2">
                    <IntegrationBrandIcon id="viber" size={16} />
                    Viber
                  </span>
                ),
              },
            ]}
          />
        }
      />
      {channelTab === "email" ? (
        <UploadEmailChannelPanel
          mailboxes={mailboxes}
          docsPerMailbox={docsPerMailbox}
          isAdmin={Boolean(isAdmin)}
          loading={loading}
          fetching={fetching}
          importBusy={importBusy}
          onAddMailbox={() => setAddOpen(true)}
          onImport={setImportMailbox}
          onFetch={(mb) => void fetchMailbox(mb)}
          onToggle={toggleMailboxActive}
          onRemove={removeMailbox}
          onReconnect={(mb) => void reconnectMailbox(mb)}
          isPollable={isMailboxPollable}
        />
      ) : channelTab === "whatsapp" ? (
        <UploadWhatsappChannelPanel docCount={docsPerChannel.whatsapp} />
      ) : channelTab === "viber" ? (
        <UploadViberChannelPanel docCount={docsPerChannel.viber} />
      ) : null}

      {channelTab === "upload" ? (
        <>
          <UploadDropZone
            className="mb-6"
            disabled={uploading}
            uploading={uploading}
            progress={uploadProgress}
            files={uploadFiles}
            onFiles={(files) => void runUpload(files)}
            onBrowse={() => uploadInputRef.current?.click()}
          />
          <DocumentMatrixPanel
            embedded
            showControls={false}
            showTable={false}
            showLegend={false}
            onFlaggedCount={setMatrixFlagged}
            refreshRef={matrixRefreshRef}
          />
          <input
            ref={uploadInputRef}
            type="file"
            accept={UPLOAD_ACCEPT}
            multiple
            className="hidden"
            data-testid="input-upload-doc"
            onChange={uploadDocuments}
          />
          {fetchNotice ? (
            <Card
              className="p-3 mb-4 text-xs text-muted-foreground border-dashed"
              role="status"
              data-testid="upload-notice"
            >
              {fetchNotice}
            </Card>
          ) : null}
          {importJob && (importJob.status === "queued" || importJob.status === "running") && (
            <Card className="p-3 mb-4 text-xs text-muted-foreground border-dashed">
              Importing mail from {importJob.from_date} through today…{" "}
              {importJob.messages_scanned > 0
                ? `${importJob.messages_scanned} message(s) scanned`
                : "scanning mailbox"}
            </Card>
          )}
        </>
      ) : null}
      {channelTab === "upload" ? (
        <PageTabs
          className="mb-5"
          value={viewTab}
          onChange={(value) => setViewTab(value as ViewTab)}
          data-testid="upload-view-tabs"
          tabs={[
            {
              value: "summary",
              testid: "tab-upload-summary",
              label: (
                <>
                  Summary
                  {matrixFlagged > 0 ? (
                    <Badge variant="destructive" className="ml-1.5 tnum font-normal">
                      {matrixFlagged}
                    </Badge>
                  ) : null}
                </>
              ),
            },
            {
              value: "detailed",
              testid: "tab-upload-detailed",
              label: (
                <>
                  Detailed
                  {inboxCount > 0 ? (
                    <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                      {inboxCount}
                    </Badge>
                  ) : null}
                </>
              ),
            },
          ]}
        />
      ) : null}
      {content}
    </div>
  );

  if (
    error &&
    channelTab === "upload" &&
    viewTab === "detailed" &&
    captured.length === 0 &&
    !loading
  ) {
    return workspaceShell(
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {formatTenantLoadError(error, UPLOAD_LOAD_HINT)}
        <code className="text-xs">(alembic upgrade head)</code>.
        <div className="mt-3">
          <Button variant="outline" size="sm" onClick={() => void refetchInvoiceList()}>
            Retry
          </Button>
        </div>
      </Card>
    );
  }

  return workspaceShell(
    channelTab === "upload" && viewTab === "summary" ? (
      <>
        <DocumentMatrixPanel
          embedded
          showKpis={false}
          onFlaggedCount={setMatrixFlagged}
          onGoUpload={() => setViewTab("detailed")}
          refreshRef={matrixRefreshRef}
        />
      </>
    ) : channelTab !== "upload" ? null : (
      <>
      <ConnectMailboxDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSendInvite={sendMailboxInvite}
      />

      <MailboxImportDialog
        open={importMailbox != null}
        mailboxEmail={importMailbox?.email ?? ""}
        busy={importBusy}
        onClose={() => setImportMailbox(null)}
        onSubmit={(payload) => void startHistoricalImport(payload)}
      />

      {loading && !showCapturedChrome ? (
        <InlineTableSkeleton rows={8} columns={6} />
      ) : !showCapturedChrome ? (
        <EmptyState
          title="No documents yet"
          hint={
            channelTab === "upload"
              ? "Upload documents from the Upload tab, or capture documents from Email, WhatsApp, or Viber."
              : "Capture documents from Email, WhatsApp, or Viber. To upload files, switch to the Upload tab."
          }
          action={
            isAdmin ? (
              <Button size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="h-4 w-4 mr-1" />
                Add mailbox
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-3 px-3 sm:px-4 py-3 border-b border-border sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-sm font-semibold flex items-center gap-2 shrink-0">
              <Mail className="h-4 w-4 text-primary" />
              Captured documents
              <span className="text-muted-foreground tnum font-normal">({totalInvoices})</span>
            </h3>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:ml-auto">
            <ListSearchInput
              value={searchQuery}
              onChange={setSearchQuery}
              placeholder="Search this list…"
              testId="input-upload-search"
              className="w-full sm:max-w-xs"
            />
            <Select
              value={evalFilter}
              onValueChange={(value) => {
                setEvalFilter(value === "needs_review" ? "needs_review" : "all");
                setPage(1);
              }}
              data-testid="select-eval-filter"
              className="w-full sm:w-[200px] h-8 text-xs"
              options={[
                { value: "all", label: "All evaluations" },
                { value: "needs_review", label: "Needs review only" },
              ]}
            />
            <Select
              value={source}
              onValueChange={(value) => {
                setSource(value);
                setPage(1);
              }}
              data-testid="select-source-filter"
              className="w-full sm:w-[220px] h-8 text-xs"
              options={[
                { value: "all", label: "All sources" },
                ...mailboxes.map((mb) => ({
                  value: mb.email,
                  label: mailboxNickname(mb),
                })),
              ]}
            />
            </div>
          </div>

          {loading && captured.length === 0 ? (
            <div className="px-3 sm:px-4 py-4">
              <InlineTableSkeleton rows={6} columns={6} />
            </div>
          ) : (
            <>
          <div className="md:hidden divide-y divide-border">
            {filtered.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                {hasActiveSearch
                  ? "No documents match your search."
                  : "No documents match this filter."}
              </p>
            )}
            {filtered.map((inv) => (
              <UploadInvoiceMobileRow
                key={inv.id}
                inv={inv}
                documentTypes={ruleBook?.documentTypes}
                processingIds={processingIds}
                onOpen={() => openDrawer(inv.id)}
                receivedLabel={relativeTime(inv.created_at)}
              />
            ))}
          </div>

          <div className="hidden md:block overflow-x-auto">
            <table className="w-full min-w-[1180px] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="px-4 py-2 font-medium">Document</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">{counterpartyColumnLabel({ mixed: true })}</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Route</th>
                  <th className="px-3 py-2 font-medium">GL account</th>
                  <th className="px-3 py-2 font-medium">Stage</th>
                  <th
                    className="px-3 py-2 font-medium"
                    title="Routing outcome after rule book evaluation"
                  >
                    Evaluation
                  </th>
                  <th className="px-3 py-2 font-medium text-right">Rule pass</th>
                  <th className="px-3 py-2 font-medium text-right">
                    {counterpartyMatchColumnLabel({ mixed: true })}
                  </th>
                  <th className="px-3 py-2 font-medium text-right">Total</th>
                  <th className="px-4 py-2 font-medium text-right">Received</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={12} className="px-4 py-8 text-center text-muted-foreground">
                      {hasActiveSearch
                        ? "No documents match your search."
                        : "No documents match this filter."}
                    </td>
                  </tr>
                )}
                {filtered.map((inv) => (
                  <UploadInvoiceTableRow
                    key={inv.id}
                    inv={inv}
                    documentTypes={ruleBook?.documentTypes}
                    processingIds={processingIds}
                    onOpen={() => openDrawer(inv.id)}
                    receivedLabel={relativeTime(inv.created_at)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-3 px-3 sm:px-4 py-3 border-t border-border">
            <p className="text-xs text-muted-foreground shrink-0">
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
            </>
          )}
        </Card>
      )}

      <InvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onUpdated={() => void invalidateUploadInvoiceList(queryClient)}
      />
      </>
    )
  );
}
