import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { CloudUpload } from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, MailboxBackfillJob } from "@/api/types";
import { ConnectMailboxDialog } from "@/components/ConnectMailboxDialog";
import { IngestionTab } from "@/components/rule-book/IngestionTab";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { useMailboxes } from "@/hooks/useMailboxes";
import { useRuleBookIngestStats } from "@/hooks/useRuleBookConfig";
import { useRuleBookDraft } from "@/hooks/useRuleBookDraft";
import { canRenderTenantOwnedUi } from "@/lib/tenantSession";
import { MailboxImportDialog } from "@/components/mailboxes/MailboxImportDialog";
import { NotificationBell } from "@/components/NotificationBell";
import { PageHeader } from "@/components/PageHeader";
import { PageTabs } from "@/components/PageTabs";
import { ListSearchInput } from "@/components/ListSearchInput";
import { AllDocumentsDetailedTable } from "@/components/upload/AllDocumentsDetailedTable";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { UploadTableFilterRail } from "@/components/upload/UploadTableFilterRail";
import { parseUploadChannelTab, type AllDocumentsChannelTab } from "@/lib/allDocumentsSummary";
import {
  EMPTY_UPLOAD_APPROVAL_COUNTS,
  approvalBoardCountsEqual,
  parseUploadApprovalFilter,
  parseUploadDocumentAreas,
  routeTargetsForDocumentAreas,
  serializeUploadApprovalFilter,
  serializeUploadDocumentAreas,
  UPLOAD_DOCUMENT_AREA_FILTERS,
  type UploadApprovalBoardCounts,
  type UploadApprovalStatusKey,
  type UploadDocumentAreaKey,
} from "@/lib/uploadApprovalFilter";
import { fetchMatrixPage } from "@/lib/matrixApi";
import { invalidateUploadInvoiceList } from "@/hooks/useUploadInvoiceList";
import {
  UploadEmailChannelPanel,
  UploadViberChannelPanel,
  UploadWhatsappChannelPanel,
} from "@/components/upload/UploadChannelPanels";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryClient";
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
import { canAccessModulePath } from "@/lib/tenantModules";
import { useTenantModules } from "@/hooks/useTenantModules";
import { isUploadRouteFilter } from "@/lib/uploadRouteFilter";

type ChannelTab = AllDocumentsChannelTab;
type ViewTab = "summary" | "setup";

function parseChannelTab(value: string | null): ChannelTab {
  return parseUploadChannelTab(value);
}

function channelHasSetupTab(channel: ChannelTab): boolean {
  return channel === "email" || channel === "whatsapp" || channel === "viber";
}

function channelEmptyTitle(channel: ChannelTab, routeLabel: string | null): string {
  if (routeLabel) return `No ${routeLabel} documents yet`;
  if (channel === "email") return "No email documents yet";
  if (channel === "whatsapp") return "No WhatsApp documents yet";
  if (channel === "viber") return "No Viber documents yet";
  return "No documents yet";
}

function channelEmptyHint(channel: ChannelTab, routeLabel: string | null): string {
  if (routeLabel) {
    return `Documents classified and routed to ${routeLabel} appear here.`;
  }
  if (channel === "all") {
    return "Upload files from the Upload tab, or capture documents from Email, WhatsApp, or Viber.";
  }
  if (channel === "upload") {
    return "Drop files above to upload, or capture documents from the Email, WhatsApp, or Viber tabs. Team expense claims use Email / WhatsApp / Viber when the sender is in Employees.";
  }
  if (channel === "email") {
    return "Connect a mailbox and fetch mail. Messages from employees in the registry route to Team Expenses.";
  }
  if (channel === "whatsapp") {
    return "Connect WhatsApp to capture employee claims (sender must match Employees).";
  }
  return "Connect Viber to capture employee claims (sender must match Employees).";
}

function parseViewTab(searchParams: URLSearchParams, channel: ChannelTab): ViewTab {
  const view = searchParams.get("view") ?? searchParams.get("tab");
  if (view === "setup" && channelHasSetupTab(channel)) return "setup";
  return "summary";
}

const PROCESSING_WAIT_MS = 120_000;
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


function isMailboxPollable(mb: ConnectedMailbox): boolean {
  return mb.is_active && mb.connection_status === "connected";
}

export function UploadPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";
  const enabledModules = useTenantModules();
  const visibleDocumentAreas = UPLOAD_DOCUMENT_AREA_FILTERS.filter((item) =>
    canAccessModulePath(item.path, enabledModules, item.moduleKey)
  ).map((item) => item.key);
  const [searchParams, setSearchParams] = useSearchParams();
  const channelTab = parseChannelTab(searchParams.get("channel"));
  const viewTab = parseViewTab(searchParams, channelTab);

  useEffect(() => {
    const view = searchParams.get("view");
    const tab = searchParams.get("tab");
    const next = new URLSearchParams(searchParams);
    let changed = false;
    const retired = new Set(["detailed"]);
    if (retired.has(view ?? "")) {
      next.delete("view");
      changed = true;
    }
    if (retired.has(tab ?? "")) {
      next.delete("tab");
      changed = true;
    }
    const viewToken = view && !retired.has(view) ? view : tab && !retired.has(tab) ? tab : null;
    if (viewToken && isUploadRouteFilter(viewToken)) {
      if (!next.get("area")) {
        const serialized = serializeUploadDocumentAreas(
          parseUploadDocumentAreas(null, viewToken)
        );
        if (serialized) next.set("area", serialized);
      }
      if (next.get("view") === viewToken) next.delete("view");
      if (next.get("tab") === viewToken) next.delete("tab");
      changed = true;
    }
    if (!changed) return;
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const showSetupTab = channelHasSetupTab(channelTab);
  const approvalParam = searchParams.get("approval");
  const approvalFilter = useMemo(
    () => parseUploadApprovalFilter(approvalParam),
    [approvalParam]
  );
  const areaParam = searchParams.get("area");
  const viewParam = searchParams.get("view");
  const documentAreas = useMemo(
    () => parseUploadDocumentAreas(areaParam, viewParam),
    [areaParam, viewParam]
  );
  const [boardCounts, setBoardCounts] = useState<UploadApprovalBoardCounts>(
    EMPTY_UPLOAD_APPROVAL_COUNTS
  );
  const setBoardCountsIfChanged = (next: UploadApprovalBoardCounts) => {
    setBoardCounts((prev) => (approvalBoardCountsEqual(prev, next) ? prev : next));
  };
  const matrixRefreshRef = useRef<(() => void) | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const {
    data: mailboxQueryData = [],
    blocked: mailboxesBlocked,
    isPending: mailboxesPending,
    refetch: refetchMailboxes,
  } = useMailboxes(Boolean(user) && channelTab === "email");
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get("q") ?? "");

  useEffect(() => {
    // Only sync when the URL explicitly carries q — do not wipe local typing when
    // other params (e.g. tab) change.
    if (!searchParams.has("q")) return;
    const q = searchParams.get("q") ?? "";
    setSearchQuery((current) => (current === q ? current : q));
  }, [searchParams]);
  const [addOpen, setAddOpen] = useState(false);
  const ingestDraftEnabled = Boolean(user) && (addOpen || channelTab === "email");
  const {
    ruleBook,
    isLoading: ingestLoading,
    canEdit: canEditIngest,
    patch: patchIngest,
  } = useRuleBookDraft(ingestDraftEnabled);
  const { data: ingestStats } = useRuleBookIngestStats(ingestDraftEnabled);
  const ingestionRules = useMemo(() => {
    const rules = ruleBook?.emailCaptureRules ?? [];
    if (!ingestStats) return rules;
    return rules.map((rule) => {
      const row = ingestStats[rule.id];
      if (!row) return rule;
      return {
        ...rule,
        matchedCount: row.matched_count,
        lastMatched: row.last_matched,
      };
    });
  }, [ingestStats, ruleBook?.emailCaptureRules]);
  const [fetching, setFetching] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ completed: number; total: number } | null>(
    null
  );
  const [fetchNotice, setFetchNotice] = useState<string | null>(null);
  const [importMailbox, setImportMailbox] = useState<ConnectedMailbox | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importJob, setImportJob] = useState<MailboxBackfillJob | null>(null);
  const tenantScope = user?.tenant_id ?? null;
  const mailboxes = canRenderTenantOwnedUi(tenantScope) && !mailboxesBlocked ? mailboxQueryData : [];
  const loading = (mailboxesPending || mailboxesBlocked) && channelTab === "email";

  useResetOnTenantChange(() => {
    setImportMailbox(null);
    setImportJob(null);
    setFetchNotice(null);
  });

  useEffect(() => {
    if (!fetchNotice || isProgressNotice(fetchNotice)) return;
    const timer = window.setTimeout(() => setFetchNotice(null), NOTICE_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [fetchNotice]);

  const docsPerMailbox = useMemo(() => {
    const counts = new Map<number, number>();
    for (const mailbox of mailboxes) {
      counts.set(mailbox.id, mailbox.document_count ?? 0);
    }
    return counts;
  }, [mailboxes]);

  useEffect(() => {
    setBoardCounts(EMPTY_UPLOAD_APPROVAL_COUNTS);
  }, [channelTab, areaParam]);

  const setChannelTab = (tab: ChannelTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "all") next.delete("channel");
    else next.set("channel", tab);
    next.delete("tab");
    if (!channelHasSetupTab(tab) && (next.get("view") === "setup" || viewTab === "setup")) {
      next.delete("view");
    }
    setSearchParams(next, { replace: true });
  };

  const setViewTab = (tab: ViewTab) => {
    const next = new URLSearchParams(searchParams);
    next.delete("tab");
    if (tab === "setup") next.set("view", "setup");
    else if (next.get("view") === "setup") next.delete("view");
    setSearchParams(next, { replace: true });
  };

  const setApprovalFilter = (value: UploadApprovalStatusKey[]) => {
    const next = new URLSearchParams(searchParams);
    const serialized = serializeUploadApprovalFilter(value);
    if (!serialized) next.delete("approval");
    else next.set("approval", serialized);
    setSearchParams(next, { replace: true });
  };

  const setDocumentAreas = (value: UploadDocumentAreaKey[]) => {
    const next = new URLSearchParams(searchParams);
    const serialized = serializeUploadDocumentAreas(value);
    if (!serialized) next.delete("area");
    else next.set("area", serialized);
    if (isUploadRouteFilter(next.get("view"))) next.delete("view");
    if (isUploadRouteFilter(next.get("tab"))) next.delete("tab");
    setSearchParams(next, { replace: true });
  };

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
      await invalidateUploadInvoiceList(queryClient);
      matrixRefreshRef.current?.();
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
    const before = await fetchMatrixPage(1, { capture_source: "email" }, true);
    const beforeIds = new Set(before.rows.map((row) => row.invoice.id));
    try {
      await api.triggerProcess(mailbox.id);
      setFetchNotice("Fetch queued — waiting for worker…");
      await waitForProcessingIdle();
      void refetchMailboxes();

      for (let attempt = 0; attempt < 20; attempt += 1) {
        const snapshot = await fetchMatrixPage(1, { capture_source: "email" }, true);
        const hasNewDoc = snapshot.rows.some((row) => !beforeIds.has(row.invoice.id));
        if (snapshot.total > before.total || hasNewDoc) {
          break;
        }
        if (attempt < 19) {
          setFetchNotice("Processing… checking for new documents");
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
      setFetchNotice(null);
      matrixRefreshRef.current?.();
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
      await invalidateUploadInvoiceList(queryClient);
      matrixRefreshRef.current?.();

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
      setUploadProgress({ completed: files.length, total: files.length });
      // Hold success tick in the dropzone before returning to idle.
      await new Promise((resolve) => window.setTimeout(resolve, 1700));

      let notice = formatBulkUploadNotice(summary);
      if (skipped > 0) {
        notice = `${skipped} unsupported file(s) skipped. ${notice}`;
      }
      if (truncated) {
        notice = `${notice} Only the first ${BULK_UPLOAD_MAX_FILES} files were uploaded.`;
      }
      setFetchNotice(notice);
      void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes() });
      await invalidateUploadInvoiceList(queryClient);
      matrixRefreshRef.current?.();
      const uploadedIds = summary.results
        .filter((row): row is Extract<BulkUploadItemResult, { ok: true }> => row.ok)
        .flatMap((row) => row.invoiceIds);
      if (uploadedIds.length > 0) {
        void (async () => {
          const holdNotice = await watchInvoiceIdsForVendorHold(uploadedIds, {
            onPoll: async () => {
              matrixRefreshRef.current?.();
            },
          });
          if (holdNotice) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.pendingVendors() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
            setFetchNotice((prev) => (prev ? `${prev} ${holdNotice}` : holdNotice));
          }
        })();
        window.setTimeout(() => {
          matrixRefreshRef.current?.();
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

  const setupPanel =
    channelTab === "email" ? (
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
      <UploadWhatsappChannelPanel docCount={boardCounts.all} />
    ) : channelTab === "viber" ? (
      <UploadViberChannelPanel docCount={boardCounts.all} />
    ) : null;

  const workspaceShell = (content: ReactNode) => (
    <div className="upload-workspace">
      <PageHeader
        headline={
          <PageTabs
            value={channelTab}
            onChange={(value) => setChannelTab(value as ChannelTab)}
            data-testid="upload-channel-tabs"
            tabs={[
              {
                value: "all",
                testid: "tab-upload-all",
                label: (
                  <span className="inline-flex items-center gap-2">
                    All Documents
                  </span>
                ),
              },
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
        actions={<NotificationBell variant="header" />}
      />
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
          <input
            ref={uploadInputRef}
            type="file"
            accept={UPLOAD_ACCEPT}
            multiple
            className="hidden"
            data-testid="input-upload-doc"
            onChange={uploadDocuments}
          />
        </>
      ) : null}
      {fetchNotice ? (
        <Card
          className="p-3 mb-4 text-xs text-muted-foreground border-dashed"
          role="status"
          data-testid="upload-notice"
        >
          {fetchNotice}
        </Card>
      ) : null}
      {importJob && (importJob.status === "queued" || importJob.status === "running") ? (
        <Card className="p-3 mb-4 text-xs text-muted-foreground border-dashed">
          Importing mail from {importJob.from_date} through today…{" "}
          {importJob.messages_scanned > 0
            ? `${importJob.messages_scanned} message(s) scanned`
            : "scanning mailbox"}
        </Card>
      ) : null}
      <div
        className={
          viewTab !== "setup"
            ? "upload-workspace__view-row upload-workspace__view-row--filters"
            : "upload-workspace__view-row"
        }
      >
        <PageTabs
          className="mb-0"
          value={viewTab}
          onChange={(value) => setViewTab(value as ViewTab)}
          data-testid="upload-view-tabs"
          tabs={[
            {
              value: "summary",
              testid: "tab-upload-summary",
              label: "Summary",
            },
            ...(showSetupTab
              ? [
                  {
                    value: "setup",
                    testid: "tab-upload-setup",
                    label: "Setup",
                  },
                ]
              : []),
          ]}
        />
        {viewTab !== "setup" ? (
          <UploadTableFilterRail
            area={documentAreas}
            onAreaChange={setDocumentAreas}
            status={approvalFilter}
            onStatusChange={setApprovalFilter}
            counts={boardCounts}
            visibleAreas={visibleDocumentAreas}
          />
        ) : null}
        {viewTab === "setup" && channelTab === "email" && isAdmin ? (
          <Button data-testid="button-add-mailbox" onClick={() => setAddOpen(true)}>
            Add mailbox
          </Button>
        ) : null}
      </div>
      {viewTab !== "setup" ? (
        <div className="upload-table-toolbar">
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search documents…"
            testId="input-all-documents-summary-search"
            className="upload-table-toolbar__search"
          />
        </div>
      ) : null}
      {content}

      <ConnectMailboxDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSendInvite={sendMailboxInvite}
        ingestion={
          <div className={!canEditIngest ? "pointer-events-none opacity-90" : undefined}>
            {ingestLoading && !ruleBook ? (
              <p className="text-sm text-muted-foreground">Loading ingestion rules…</p>
            ) : (
              <IngestionTab
                compact
                rules={ingestionRules}
                onChange={(emailCaptureRules) => patchIngest({ emailCaptureRules })}
              />
            )}
          </div>
        }
      />
      <MailboxImportDialog
        open={importMailbox != null}
        mailboxEmail={importMailbox?.email ?? ""}
        busy={importBusy}
        onClose={() => setImportMailbox(null)}
        onSubmit={(payload) => void startHistoricalImport(payload)}
      />
    </div>
  );

  const channelCaptureSource =
    channelTab === "all" ? undefined : channelTab;
  const showUploadSourceColumn = channelTab === "all";
  const documentRouteTarget = routeTargetsForDocumentAreas(documentAreas);
  const routeLabel = documentRouteTarget ?? null;

  return workspaceShell(
    viewTab === "setup" ? (
      setupPanel
    ) : (
      <AllDocumentsDetailedTable
        captureSource={channelCaptureSource}
        routeTarget={documentRouteTarget}
        showUploadSource={showUploadSourceColumn}
        showSearchHeader={false}
        emptyTitle={channelEmptyTitle(channelTab, routeLabel)}
        emptyHint={channelEmptyHint(channelTab, routeLabel)}
        onGoUpload={
          channelTab === "all" || channelTab === "upload"
            ? () => setChannelTab("upload")
            : undefined
        }
        refreshRef={matrixRefreshRef}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        approvalBoardColumns={approvalFilter}
        onBoardCounts={setBoardCountsIfChanged}
      />
    )
  );
}
