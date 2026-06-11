import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Mail, Pause, Play, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, Invoice } from "@/api/types";
import { ConnectMailboxDialog } from "@/components/ConnectMailboxDialog";
import { EmptyState } from "@/components/EmptyState";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";
import {
  EvaluationStatusBadge,
  RouteTargetBadge,
} from "@/components/inbox/EvaluationStatusBadge";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { InboxSourceBadge } from "@/components/inbox/InboxSourceBadge";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { inboxStage, StageBadge } from "@/components/StageBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { invId, money } from "@/lib/format";
import {
  invoiceDocumentType,
  invoiceDocumentTypeLabel,
  invoiceMatchesMailbox,
  invoiceSourceKind,
  invoiceValidationConfidence,
  invoiceVendorConfidence,
  mailboxDisplayName,
} from "@/lib/invoice";
import { fetchAllInvoices } from "@/lib/invoices";
import { cn } from "@/lib/cn";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";

const INBOX_POLL_MS = 15_000;
const UPLOAD_ACCEPT = ".pdf,.jpg,.jpeg,.png,.docx";
const PIPELINE_STATUSES = new Set([
  "pending",
  "parsing",
  "validating",
  "mapping",
  "journaling",
  "reconciling",
]);
const PROCESSING_WAIT_MS = 120_000;

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

async function waitForInvoicePipeline(
  invoiceId: number,
  timeoutMs = PROCESSING_WAIT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const inv = await api.getInvoice(invoiceId);
    if (!PIPELINE_STATUSES.has(inv.status)) {
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

export function InboxPage() {
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [all, setAll] = useState<Invoice[]>([]);
  const [mailboxes, setMailboxes] = useState<ConnectedMailbox[]>([]);
  const [totalInvoices, setTotalInvoices] = useState(0);
  const [source, setSource] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [fetching, setFetching] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [fetchNotice, setFetchNotice] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const fresh = options?.fresh ?? !options?.silent;
      const [invoiceRows, mbs] = await Promise.all([
        fetchAllInvoices(fresh),
        api.listMailboxes({ fresh }).catch(() => [] as ConnectedMailbox[]),
      ]);
      setAll(invoiceRows);
      setTotalInvoices(invoiceRows.length);
      setMailboxes(mbs);
      return {
        total: invoiceRows.length,
        ids: invoiceRows.map((i) => i.id),
      };
    } catch (e) {
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load inbox");
        setAll([]);
        setMailboxes([]);
      }
      return null;
    } finally {
      if (!options?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, INBOX_POLL_MS);

  const captured = useMemo(
    () => all.filter((r) => r.status !== "duplicate_skipped"),
    [all]
  );

  const filtered = useMemo(() => {
    if (source === "all") return captured;
    const mb = mailboxes.find((m) => m.email === source);
    if (!mb) return captured;
    return captured.filter((i) => invoiceMatchesMailbox(i, mb.id));
  }, [captured, source, mailboxes]);

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

  async function sendMailboxInvite(body: {
    email: string;
    display_name?: string;
    message?: string;
  }) {
    await api.createMailboxConnectionRequest(body);
    setFetchNotice(`Invitation sent to ${body.email}`);
  }

  function applyMailboxUpdate(updated: ConnectedMailbox) {
    setMailboxes((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
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
      setMailboxes((prev) => prev.filter((m) => m.id !== mb.id));
      if (source === mb.email) {
        setSource("all");
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
        const hasNewDoc =
          snapshot?.ids.some((id) => !beforeIds.has(id)) ?? false;
        if (latestTotal > beforeTotal || hasNewDoc) break;
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

  async function uploadDocument(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    setUploading(true);
    setFetchNotice(null);
    try {
      const inv = await api.uploadInvoice(file);
      setFetchNotice("Document uploaded — processing…");
      await waitForInvoicePipeline(inv.id);
      await load({ fresh: true });
      setFetchNotice(null);
      openDrawer(inv.id);
    } catch (err) {
      setFetchNotice(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  if (error) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error}. Ensure the API is running on port 8001.
      </Card>
    );
  }

  return (
    <div>
      <PageHeader
        title="Inbox"
        subtitle="Documents captured from connected mailboxes, uploads and the vault."
        actions={
          <>
            <Button
              variant="outline"
              disabled={uploading}
              onClick={() => uploadInputRef.current?.click()}
              data-testid="button-upload-doc"
            >
              <Upload className="h-4 w-4 mr-1" />
              {uploading ? "Uploading…" : "Upload doc"}
            </Button>
            <Button data-testid="button-add-mailbox" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4 mr-1" />
              Add mailbox
            </Button>
          </>
        }
      />

      <ConnectMailboxDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSendInvite={sendMailboxInvite}
      />

      <input
        ref={uploadInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        className="hidden"
        data-testid="input-upload-doc"
        onChange={uploadDocument}
      />

      {fetchNotice && (
        <Card className="p-3 mb-4 text-xs text-muted-foreground border-dashed">{fetchNotice}</Card>
      )}

      {mailboxes.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-6">
          {mailboxes.map((mb) => {
            const docCount = docsPerMailbox.get(mb.id) ?? 0;
            return (
              <Card key={mb.id} className="p-4" data-testid={`card-mailbox-${mb.email}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
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
                <div className="flex items-center justify-between mt-3 text-xs text-muted-foreground">
                  <span>
                    {mailboxProvider(mb)} · {relativeTime(mb.last_poll_at)}
                  </span>
                  <span className="tnum">{docCount} docs</span>
                </div>
                <div className="flex items-center gap-1.5 mt-3">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    data-testid={`button-fetch-${mb.email}`}
                    disabled={fetching === mb.email}
                    onClick={() => void fetchMailbox(mb)}
                  >
                    <RefreshCw
                      className={cn("h-3 w-3 mr-1", fetching === mb.email && "animate-spin")}
                    />
                    Fetch
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    data-testid={`button-toggle-${mb.email}`}
                    onClick={() => toggleMailboxActive(mb)}
                  >
                    {mb.is_active ? (
                      <Pause className="h-3 w-3 mr-1" />
                    ) : (
                      <Play className="h-3 w-3 mr-1" />
                    )}
                    {mb.is_active ? "Pause" : "Resume"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive ml-auto"
                    data-testid={`button-remove-${mb.email}`}
                    onClick={() => removeMailbox(mb)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        !loading && (
          <Card className="p-4 mb-6 text-sm text-muted-foreground">
            No mailboxes connected yet.{" "}
            <button
              type="button"
              className="text-primary hover:underline"
              onClick={() => setAddOpen(true)}
            >
              Add a mailbox
            </button>
          </Card>
        )
      )}

      {loading && captured.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading inbox…</Card>
      ) : captured.length === 0 ? (
        <EmptyState
          title="Inbox is empty"
          hint="Connect a mailbox and fetch, or upload an invoice PDF from this page."
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={uploading}
                onClick={() => uploadInputRef.current?.click()}
                data-testid="button-upload-doc"
              >
                <Upload className="h-4 w-4 mr-1" />
                {uploading ? "Uploading…" : "Upload doc"}
              </Button>
              <Button size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="h-4 w-4 mr-1" />
                Add mailbox
              </Button>
            </div>
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border flex-wrap">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Mail className="h-4 w-4 text-primary" />
              Captured documents
              <span className="text-muted-foreground tnum font-normal">({filtered.length})</span>
            </h3>
            <div className="flex items-center gap-2 ml-auto">
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                disabled={uploading}
                onClick={() => uploadInputRef.current?.click()}
                data-testid="button-upload-doc-toolbar"
              >
                <Upload className="h-3.5 w-3.5 mr-1" />
                {uploading ? "Uploading…" : "Upload"}
              </Button>
            <Select
              value={source}
              onValueChange={setSource}
              data-testid="select-source-filter"
              className="w-[220px] h-8 text-xs"
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

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="px-4 py-2 font-medium">Document</th>
                  <th className="px-3 py-2 font-medium">Vendor</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Route</th>
                  <th className="px-3 py-2 font-medium">GL account</th>
                  <th className="px-3 py-2 font-medium">Stage</th>
                  <th className="px-3 py-2 font-medium">Evaluation</th>
                  <th className="px-3 py-2 font-medium text-right">VR pass</th>
                  <th className="px-3 py-2 font-medium text-right">Vendor</th>
                  <th className="px-3 py-2 font-medium text-right">Total</th>
                  <th className="px-4 py-2 font-medium text-right">Received</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground">
                      No documents match this filter.
                    </td>
                  </tr>
                )}
                {filtered.map((inv) => (
                  <tr
                    key={inv.id}
                    data-testid={`row-invoice-${inv.id}`}
                    className="row-band border-b border-border/60 cursor-pointer hover-elevate last:border-0"
                    onClick={() => openDrawer(inv.id)}
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{invId(inv.id)}</div>
                      <div className="text-xs text-muted-foreground tnum">
                        {inv.invoice_no ?? `DOC-${inv.id}`} ·{" "}
                        {invoiceDocumentTypeLabel(invoiceDocumentType(inv))}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 max-w-[160px] truncate">{inv.vendor ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      <InboxSourceBadge kind={invoiceSourceKind(inv)} />
                    </td>
                    <td className="px-3 py-2.5">
                      <RouteTargetBadge route={inv.route_target} />
                    </td>
                    <td className="px-3 py-2.5">
                      <InboxGlAccountBadge account={inv.account_name} />
                    </td>
                    <td className="px-3 py-2.5">
                      <StageBadge stage={inboxStage(inv)} />
                    </td>
                    <td className="px-3 py-2.5">
                      <EvaluationStatusBadge status={inv.evaluation_status} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <InboxConfidenceBadge value={invoiceValidationConfidence(inv)} />
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <InboxConfidenceBadge value={invoiceVendorConfidence(inv)} />
                    </td>
                    <td className="px-3 py-2.5 text-right tnum font-medium">
                      {money(inv.total, inv.currency)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-muted-foreground tnum">
                      {relativeTime(inv.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <InvoiceDetailDrawer
        invoiceId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onUpdated={() => load({ fresh: true })}
      />
    </div>
  );
}
