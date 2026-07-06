import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Mail, Pause, Play, Plus, RefreshCw, Trash2, Calendar } from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, Invoice, MailboxBackfillJob } from "@/api/types";
import { ConnectMailboxDialog } from "@/components/ConnectMailboxDialog";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { useMailboxes } from "@/hooks/useMailboxes";
import {
  API_PORT_HINT,
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
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
import { cn } from "@/lib/cn";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { useNavBadges } from "@/hooks/useNavBadges";
import { ActionChip } from "@/components/ActionChip";
import { UploadDropZone } from "@/components/upload/UploadDropZone";
import {
  UploadInvoiceMobileRow,
  UploadInvoiceTableRow,
} from "@/components/upload/UploadInvoiceListRow";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryClient";
import { mergeBoardRowWithLocal, shouldClearProcessingId } from "@/lib/approvalsBoard";
import {
  BULK_UPLOAD_MAX_FILES,
  filterUploadFiles,
  formatBulkUploadNotice,
  type BulkUploadItemResult,
  UPLOAD_ACCEPT,
  uploadFilesInBatch,
  watchInvoiceIdsForVendorHold,
} from "@/lib/bulkUpload";
import { uploadListHasActiveProcessing } from "@/lib/uploadColumnState";

const UPLOAD_LOAD_HINT =
  `${API_PORT_HINT.trim()} and migrations are up to date `;
const INBOX_POLL_MS = 15_000;
const INBOX_POLL_FAST_MS = 4_000;
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

function mailboxProvider(mb: ConnectedMailbox): string {
  if (mb.mail_provider === "google") return "Gmail";
  if (mb.mail_provider === "microsoft") return "Outlook";
  const label = `${mb.display_name ?? ""} ${mb.email}`.toLowerCase();
  if (label.includes("imap")) return "IMAP";
  if (
    label.includes("outlook") ||
    label.includes("office365") ||
    label.includes("microsoft")
  ) {
    return "Outlook";
  }
  if (label.includes("exchange")) return "Exchange";
  return "Gmail";
}

function mailboxNickname(mb: ConnectedMailbox): string {
  const label = mb.display_name?.trim();
  if (label && !label.includes("@") && !label.includes("(")) {
    return label;
  }
  return mailboxDisplayName(mb.email, mb.display_name);
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
  const workspaceTab = searchParams.get("tab") === "matrix" ? "matrix" : "upload";
  const { data: navBadges } = useNavBadges();
  const [matrixFlagged, setMatrixFlagged] = useState(0);
  const matrixRefreshRef = useRef<(() => void) | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const loadSeq = useRef(0);
  const loadInFlightRef = useRef(false);
  const mailboxesRef = useRef<ConnectedMailbox[]>([]);
  const initialLoadDoneRef = useRef(false);
  const { data: ruleBook } = useRuleBookConfig();
  const {
    data: mailboxQueryData = [],
    blocked: mailboxesBlocked,
    refetch: refetchMailboxes,
  } = useMailboxes(Boolean(user) && workspaceTab === "upload");
  const [all, setAll] = useState<Invoice[]>([]);
  const [totalInvoices, setTotalInvoices] = useState(0);
  const [source, setSource] = useState("all");
  const [evalFilter, setEvalFilter] = useState<"all" | "needs_review">("all");
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get("q") ?? "");
  const debouncedSearch = useDebouncedValue(searchQuery.trim());

  useEffect(() => {
    const q = searchParams.get("q") ?? "";
    setSearchQuery((current) => (current === q ? current : q));
  }, [searchParams]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [fetching, setFetching] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
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
  const [totalPages, setTotalPages] = useState(1);
  const [processingIds, setProcessingIds] = useState<Set<number>>(() => new Set());
  const processingIdsRef = useRef(processingIds);
  const tenantScope = user?.tenant_id ?? null;
  const mailboxes = canRenderTenantOwnedUi(tenantScope) && !mailboxesBlocked ? mailboxQueryData : [];

  useLayoutEffect(() => {
    mailboxesRef.current = [];
    if (source !== "all" && !mailboxes.some((mb) => mb.email === source)) {
      setSource("all");
    }
  }, [tenantScope, mailboxes, source]);

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    initialLoadDoneRef.current = false;
    mailboxesRef.current = [];
    setAll([]);
    setTotalInvoices(0);
    setTotalPages(1);
    setPage(1);
    setSource("all");
    setError(null);
    setDrawerId(null);
    setDrawerOpen(false);
    setLoading(true);
    setImportMailbox(null);
    setImportJob(null);
    setFetchNotice(null);
    setProcessingIds(new Set());
  });

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!canRenderTenantOwnedUi(tenantScope)) return null;
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
    const refreshMailboxes = !options?.silent;
    try {
      // Prefer cached mailboxes for filter id (develop perf); never use them across tenants.
      const cachedMailboxes = isTenantFetchScopeCurrent(scope) ? mailboxesRef.current : [];
      const selectedMailboxId =
        source === "all"
          ? null
          : (cachedMailboxes.find((m) => m.email === source)?.id ?? null);
      const invoiceParams = {
        page: String(page),
        page_size: String(PAGE_SIZE),
        ...(selectedMailboxId != null
          ? { connected_mailbox_id: String(selectedMailboxId) }
          : {}),
        ...(debouncedSearch ? { q: debouncedSearch } : {}),
      };
      const invoiceRes = await api.listInvoicesWithMeta(invoiceParams, { fresh });
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return null;
      const invoiceRows = invoiceRes.data;
      const metaTotal = invoiceRes.meta?.total ?? invoiceRows.length;
      const metaPages = invoiceRes.meta?.pages ?? 1;
      setAll((prev) => {
        const prevById = new Map(prev.map((inv) => [inv.id, inv]));
        const merged = invoiceRows.map((row) =>
          mergeBoardRowWithLocal(row, prevById.get(row.id), processingIdsRef.current)
        );
        return sameUploadListRows(prev, merged) ? prev : merged;
      });
      setTotalInvoices(metaTotal);
      setTotalPages(Math.max(1, metaPages));
      setError(null);
      initialLoadDoneRef.current = true;

      if (refreshMailboxes) {
        void refetchMailboxes();
      }

      return {
        total: metaTotal,
        ids: invoiceRows.map((i) => i.id),
      };
    } catch (e) {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return null;
      if (
        handleTenantScopedLoadFailure(e, {
          retry: () => {
            void load({ silent: true, fresh: true });
          },
        })
      ) {
        return null;
      }
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load documents");
        setAll([]);
        mailboxesRef.current = [];
      }
      return null;
    } finally {
      if (options?.silent) {
        loadInFlightRef.current = false;
      }
      if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope) && !options?.silent) {
        setLoading(false);
      }
    }
  }, [page, source, debouncedSearch, tenantScope, refetchMailboxes]);

  useEffect(() => {
    mailboxesRef.current = mailboxes;
  }, [mailboxes]);

  useEffect(() => {
    processingIdsRef.current = processingIds;
  }, [processingIds]);

  useEffect(() => {
    setPage(1);
  }, [source, debouncedSearch]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const inboxPollMs = useMemo(
    () =>
      uploadListHasActiveProcessing(filtered, processingIds)
        ? INBOX_POLL_FAST_MS
        : INBOX_POLL_MS,
    [filtered, processingIds]
  );

  useVisibilityPolling(() => {
    if (!initialLoadDoneRef.current) return;
    const processing = uploadListHasActiveProcessing(filtered, processingIdsRef.current);
    void load({ silent: true, fresh: processing });
  }, inboxPollMs);

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

  const setWorkspaceTab = (tab: "upload" | "matrix") => {
    const next = new URLSearchParams(searchParams);
    if (tab === "matrix") next.set("tab", "matrix");
    else next.delete("tab");
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
      await load({ silent: true, fresh: true });
    } catch (e) {
      setFetchNotice(e instanceof Error ? e.message : "Failed to remove mailbox");
    }
  }

  async function fetchMailbox(mailbox: ConnectedMailbox) {
    setFetching(mailbox.email);
    setFetchNotice(null);
    const beforeTotal = totalInvoices;
    const beforeIds = new Set(all.map((i) => i.id));
    try {
      await api.triggerProcess(mailbox.id);
      setFetchNotice("Fetch queued — waiting for worker…");
      await waitForProcessingIdle();

      let latestTotal = beforeTotal;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        const snapshot = await load({ silent: true, fresh: true });
        if (snapshot != null) latestTotal = snapshot.total;
        const hasNewDoc = snapshot?.ids.some((id) => !beforeIds.has(id)) ?? false;
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
    } finally {
      setFetching(null);
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
      await load({ fresh: true });

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
      await load({ silent: true, fresh: true });
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
              await load({ silent: true, fresh: true });
            },
          });
          if (holdNotice) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.pendingVendors() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
            setFetchNotice((prev) => (prev ? `${prev} ${holdNotice}` : holdNotice));
          }
        })();
        window.setTimeout(() => {
          void load({ silent: true, fresh: true });
        }, 3000);
      }
    } catch (err) {
      setFetchNotice(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
  }

  async function uploadDocuments(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (selected.length === 0) return;
    await runUpload(selected);
  }

  const workspaceShell = (content: ReactNode) => (
    <div>
      <PageHeader
        title="Documents"
        subtitle={
          workspaceTab === "upload"
            ? "Documents captured from connected mailboxes, uploads and the vault."
            : "Pipeline stage status, anomaly detection, and payment readiness. Flagged documents are blocked from progressing until cleared."
        }
        actions={
          workspaceTab === "upload" && isAdmin ? (
            <Button data-testid="button-add-mailbox" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5 shrink-0" />
              Add mailbox
            </Button>
          ) : workspaceTab === "upload" ? null : (
            <Button
              variant="outline"
              size="sm"
              data-testid="button-matrix-refresh"
              onClick={() => matrixRefreshRef.current?.()}
            >
              <RefreshCw className="h-4 w-4 mr-1" />
              Refresh
            </Button>
          )
        }
      />
      <PageTabs
        className="mb-5"
        value={workspaceTab}
        onChange={(value) => setWorkspaceTab(value as "upload" | "matrix")}
        data-testid="upload-workspace-tabs"
        tabs={[
          {
            value: "upload",
            testid: "tab-upload-inbox",
            label: (
              <>
                Upload
                {inboxCount > 0 ? (
                  <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                    {inboxCount}
                  </Badge>
                ) : null}
              </>
            ),
          },
          {
            value: "matrix",
            testid: "tab-upload-matrix",
            label: (
              <>
                Doc. Matrix
                {matrixFlagged > 0 ? (
                  <Badge variant="destructive" className="ml-1.5 tnum font-normal">
                    {matrixFlagged}
                  </Badge>
                ) : null}
              </>
            ),
          },
        ]}
      />
      {content}
    </div>
  );

  if (error && workspaceTab === "upload" && captured.length === 0 && !loading) {
    return workspaceShell(
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {formatTenantLoadError(error, UPLOAD_LOAD_HINT)}
        <code className="text-xs">(alembic upgrade head)</code>.
        <div className="mt-3">
          <Button variant="outline" size="sm" onClick={() => void load({ fresh: true })}>
            Retry
          </Button>
        </div>
      </Card>
    );
  }

  return workspaceShell(
    workspaceTab === "matrix" ? (
      <DocumentMatrixPanel
        embedded
        onFlaggedCount={setMatrixFlagged}
        onGoUpload={() => setWorkspaceTab("upload")}
        refreshRef={matrixRefreshRef}
      />
    ) : (
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

      <UploadDropZone
        className="mb-6"
        disabled={uploading}
        uploading={uploading}
        progress={uploadProgress}
        onFiles={(files) => void runUpload(files)}
        onBrowse={() => uploadInputRef.current?.click()}
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

      {mailboxes.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-6">
          {mailboxes.map((mb) => {
            const docCount = docsPerMailbox.get(mb.id) ?? 0;
            return (
              <Card key={mb.id} className="p-4 min-w-0" data-testid={`card-mailbox-${mb.email}`}>
                <div className="flex items-start justify-between gap-2 min-w-0">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <Mail className="h-4 w-4 text-primary shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium text-sm truncate">{mailboxNickname(mb)}</p>
                      <p className="text-xs text-muted-foreground truncate tnum">{mb.email}</p>
                    </div>
                  </div>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-md border px-2.5 py-0.5 text-[10px] font-semibold shrink-0",
                      mb.connection_status === "connected" && mb.is_active
                        ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                        : mb.connection_status === "error"
                          ? "text-destructive border-destructive/40"
                          : "text-muted-foreground border-border"
                    )}
                  >
                    {mb.connection_status === "connected"
                      ? mb.is_active
                        ? "Connected"
                        : "Paused"
                      : mb.connection_status === "error"
                        ? "Error"
                        : "Disconnected"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 mt-3 text-xs text-muted-foreground min-w-0">
                  <span className="truncate">
                    {mailboxProvider(mb)} · {relativeTime(mb.last_poll_at)}
                  </span>
                  <span className="tnum shrink-0">{docCount} docs</span>
                </div>
                <div className="mt-3 flex items-center gap-1.5 min-w-0">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                    <ActionChip
                      tone="edit"
                      icon={Calendar}
                      label="Import"
                      testId={`button-import-${mb.email}`}
                      disabled={importBusy || fetching === mb.email}
                      onClick={() => setImportMailbox(mb)}
                    />
                    <ActionChip
                      tone="post"
                      icon={RefreshCw}
                      label="Fetch"
                      testId={`button-fetch-${mb.email}`}
                      disabled={fetching === mb.email || importBusy}
                      iconClassName={fetching === mb.email ? "animate-spin" : undefined}
                      onClick={() => void fetchMailbox(mb)}
                    />
                    {isAdmin ? (
                      <ActionChip
                        tone={mb.is_active ? "pending" : "approve"}
                        icon={mb.is_active ? Pause : Play}
                        label={mb.is_active ? "Pause" : "Resume"}
                        testId={`button-toggle-${mb.email}`}
                        onClick={() => toggleMailboxActive(mb)}
                      />
                    ) : null}
                  </div>
                  {isAdmin ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0 text-destructive"
                    data-testid={`button-remove-${mb.email}`}
                    onClick={() => removeMailbox(mb)}
                    aria-label={`Remove ${mb.email}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                  ) : null}
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        !loading && (
          <Card className="p-4 mb-6 text-sm text-muted-foreground">
            No mailboxes connected yet.{" "}
            {isAdmin ? (
              <>
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => setAddOpen(true)}
                >
                  Add a mailbox
                </button>{" "}
                or manage invitations in{" "}
                <Link to="/integrations" className="text-primary hover:underline">
                  Integrations
                </Link>
                .
              </>
            ) : (
              <>
                Ask an admin to connect a mailbox from{" "}
                <Link to="/integrations" className="text-primary hover:underline">
                  Integrations
                </Link>
                .
              </>
            )}
          </Card>
        )
      )}

      {loading && captured.length === 0 ? (
        <InlineTableSkeleton rows={8} columns={6} />
      ) : captured.length === 0 ? (
        <EmptyState
          title="No documents yet"
          hint="Drop files in the panel above, or connect a mailbox and fetch from email."
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

          <div className="md:hidden divide-y divide-border">
            {filtered.length === 0 && (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                No documents match this filter.
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
            <table className="w-full min-w-[1080px] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="px-4 py-2 font-medium">Document</th>
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
                    <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground">
                      No documents match this filter.
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
        </Card>
      )}

      <InvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onUpdated={() => load({ fresh: true })}
      />
      </>
    )
  );
}
