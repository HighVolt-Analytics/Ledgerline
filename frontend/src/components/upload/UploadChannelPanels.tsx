import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Calendar,
  ChevronDown,
  ChevronRight,
  EllipsisVertical,
  Mail,
  Pause,
  Play,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, ViberConnection, WhatsappConnection } from "@/api/types";
import { ActionChip } from "@/components/ActionChip";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { MailboxIngestionRulesPanel } from "@/components/upload/MailboxIngestionRulesPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { orphanedMailboxRules } from "@/lib/emailIngestionRules";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/cn";
import { mailboxDisplayName } from "@/lib/invoice";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";

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

function connectionStatusLabel(status: string, active = true): string {
  if (status === "connected") return active ? "Connected" : "Paused";
  if (status === "error") return "Error";
  return "Disconnected";
}

function statusBadgeClass(status: string, active = true): string {
  if (status === "connected" && active) {
    return "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]";
  }
  if (status === "error") return "text-destructive border-destructive/40";
  return "text-muted-foreground border-border";
}

function MailboxOverflowMenu({
  email,
  isAdmin,
  importBusy,
  fetching,
  pollable,
  showReconnect,
  onImport,
  onFetch,
  onRemove,
  onReconnect,
}: {
  email: string;
  isAdmin: boolean;
  importBusy: boolean;
  fetching: boolean;
  pollable: boolean;
  showReconnect: boolean;
  onImport: () => void;
  onFetch: () => void;
  onRemove: () => void;
  onReconnect: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        aria-label={`More actions for ${email}`}
        aria-expanded={open}
        data-testid={`button-mailbox-more-${email}`}
        onClick={() => setOpen((v) => !v)}
      >
        <EllipsisVertical className="h-4 w-4" />
      </Button>
      {open ? (
        <div
          className="absolute right-0 top-full z-30 mt-1 min-w-[9.5rem] rounded-md border border-border bg-card py-1 shadow-md"
          role="menu"
        >
          {showReconnect ? (
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted disabled:opacity-50"
              data-testid={`button-reconnect-${email}`}
              disabled={importBusy || fetching}
              onClick={() => {
                setOpen(false);
                onReconnect();
              }}
            >
              <Mail className="h-3.5 w-3.5 shrink-0" />
              Reconnect
            </button>
          ) : null}
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted disabled:opacity-50"
            data-testid={`button-import-${email}`}
            disabled={importBusy || fetching || !pollable}
            onClick={() => {
              setOpen(false);
              onImport();
            }}
          >
            <Calendar className="h-3.5 w-3.5 shrink-0" />
            Import
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-muted disabled:opacity-50"
            data-testid={`button-fetch-${email}`}
            disabled={fetching || importBusy || !pollable}
            onClick={() => {
              setOpen(false);
              onFetch();
            }}
          >
            <RefreshCw className={cn("h-3.5 w-3.5 shrink-0", fetching && "animate-spin")} />
            Fetch
          </button>
          {isAdmin ? (
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-destructive hover:bg-muted disabled:opacity-50"
              data-testid={`button-remove-${email}`}
              onClick={() => {
                setOpen(false);
                onRemove();
              }}
            >
              <Trash2 className="h-3.5 w-3.5 shrink-0" />
              Delete
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type EmailPanelProps = {
  mailboxes: ConnectedMailbox[];
  docsPerMailbox: Map<number, number>;
  isAdmin: boolean;
  loading: boolean;
  fetching: string | null;
  importBusy: boolean;
  onAddMailbox: () => void;
  onImport: (mailbox: ConnectedMailbox) => void;
  onFetch: (mailbox: ConnectedMailbox) => void;
  onToggle: (mailbox: ConnectedMailbox) => void;
  onRemove: (mailbox: ConnectedMailbox) => void;
  onReconnect: (mailbox: ConnectedMailbox) => void;
  isPollable: (mailbox: ConnectedMailbox) => boolean;
  ingestionRules?: EmailCaptureRule[];
  ingestionRuleWarnings?: Record<string, string[]>;
  onIngestionRulesChange?: (rules: EmailCaptureRule[]) => void;
  canEditIngestionRules?: boolean;
  ingestionRulesLoading?: boolean;
};

export function UploadEmailChannelPanel({
  mailboxes,
  docsPerMailbox,
  isAdmin,
  loading,
  fetching,
  importBusy,
  onAddMailbox,
  onImport,
  onFetch,
  onToggle,
  onRemove,
  onReconnect,
  isPollable,
  ingestionRules = [],
  ingestionRuleWarnings = {},
  onIngestionRulesChange,
  canEditIngestionRules = false,
  ingestionRulesLoading = false,
}: EmailPanelProps) {
  const [expandedMailboxId, setExpandedMailboxId] = useState<number | null>(null);
  const showIngestionRules = Boolean(onIngestionRulesChange);
  const connectedMailboxEmails = mailboxes.map((mb) => mb.email);
  const orphanedRules =
    showIngestionRules && onIngestionRulesChange
      ? orphanedMailboxRules(ingestionRules, connectedMailboxEmails)
      : [];

  useEffect(() => {
    if (expandedMailboxId == null) return;
    if (!mailboxes.some((mailbox) => mailbox.id === expandedMailboxId)) {
      setExpandedMailboxId(null);
    }
  }, [expandedMailboxId, mailboxes]);
  if (mailboxes.length === 0) {
    if (loading) return null;
    return (
      <Card className="p-4 mb-3 text-sm text-muted-foreground">
        No mailboxes connected yet.{" "}
        {isAdmin ? (
          <>
            <button type="button" className="text-primary hover:underline" onClick={onAddMailbox}>
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
    );
  }

  return (
    <div className="flex flex-col gap-2 mb-3">
      {orphanedRules.length > 0 ? (
        <Card
          className="border-amber-500/30 bg-amber-500/5 px-3 py-2.5"
          data-testid="orphaned-ingestion-rules-banner"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-medium text-amber-950 dark:text-amber-50">
                {orphanedRules.length} stale ingestion rule(s) for disconnected mailboxes
              </p>
              <ul className="text-xs text-muted-foreground space-y-0.5">
                {orphanedRules.map((rule) => (
                  <li key={rule.id}>
                    <span className="font-medium text-foreground">{rule.name}</span>
                    {" · "}
                    <span className="font-mono">{rule.mailbox}</span>
                  </li>
                ))}
              </ul>
              <p className="text-[11px] text-muted-foreground">
                These rules are stored in your tenant but ignored at ingest because the mailbox is not connected.
              </p>
            </div>
            {canEditIngestionRules ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0 h-8 text-xs"
                data-testid="button-remove-orphaned-ingestion-rules"
                onClick={() => {
                  const staleIds = new Set(orphanedRules.map((rule) => rule.id));
                  onIngestionRulesChange?.(
                    ingestionRules.filter((rule) => !staleIds.has(rule.id))
                  );
                }}
              >
                Remove stale rules
              </Button>
            ) : null}
          </div>
        </Card>
      ) : null}
      {mailboxes.map((mb) => {
        const docCount = docsPerMailbox.get(mb.id) ?? 0;
        const expanded = expandedMailboxId === mb.id;
        return (
          <Card key={mb.id} className="min-w-0 overflow-hidden" data-testid={`card-mailbox-${mb.email}`}>
            <div className="px-3 py-2.5">
              <div className="flex items-center gap-3 min-w-0">
                {showIngestionRules ? (
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    aria-expanded={expanded}
                    data-testid={`button-mailbox-rules-${mb.email}`}
                    onClick={() =>
                      setExpandedMailboxId((current) => (current === mb.id ? null : mb.id))
                    }
                  >
                    {expanded ? (
                      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <Mail className="h-4 w-4 text-primary shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium text-[14px] leading-snug truncate">{mailboxNickname(mb)}</p>
                      <p className="text-[13px] leading-snug text-muted-foreground truncate tnum">{mb.email}</p>
                      <p className="text-[12px] leading-snug text-muted-foreground truncate">
                        {mailboxProvider(mb)} · {relativeTime(mb.last_poll_at)}
                        {showIngestionRules ? " · Ingestion rules" : null}
                      </p>
                    </div>
                  </button>
                ) : (
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <Mail className="h-4 w-4 text-primary shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium text-[14px] leading-snug truncate">{mailboxNickname(mb)}</p>
                      <p className="text-[13px] leading-snug text-muted-foreground truncate tnum">{mb.email}</p>
                      <p className="text-[12px] leading-snug text-muted-foreground truncate">
                        {mailboxProvider(mb)} · {relativeTime(mb.last_poll_at)}
                      </p>
                    </div>
                  </div>
                )}
              {mb.connection_status === "error" && mb.last_error ? (
                <p
                  className="hidden sm:block max-w-[12rem] text-xs text-destructive truncate"
                  title={mb.last_error}
                >
                  {mb.last_error}
                </p>
              ) : null}
              <span
                className={cn(
                  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-[10px] font-semibold shrink-0",
                  statusBadgeClass(mb.connection_status, mb.is_active)
                )}
              >
                {connectionStatusLabel(mb.connection_status, mb.is_active)}
              </span>
              <span className="tnum text-xs text-foreground shrink-0 whitespace-nowrap">
                {docCount} docs
              </span>
              <span className="h-4 w-px shrink-0 bg-border" aria-hidden />
              {isAdmin ? (
                <ActionChip
                  tone={mb.is_active ? "pending" : "approve"}
                  icon={mb.is_active ? Pause : Play}
                  label={mb.is_active ? "Pause" : "Resume"}
                  testId={`button-toggle-${mb.email}`}
                  onClick={() => onToggle(mb)}
                />
              ) : null}
              <MailboxOverflowMenu
                email={mb.email}
                isAdmin={isAdmin}
                importBusy={importBusy}
                fetching={fetching === mb.email}
                pollable={isPollable(mb)}
                showReconnect={mb.connection_status === "error" && isAdmin}
                onImport={() => onImport(mb)}
                onFetch={() => onFetch(mb)}
                onRemove={() => onRemove(mb)}
                onReconnect={() => onReconnect(mb)}
              />
              </div>
            </div>
            {expanded && showIngestionRules && onIngestionRulesChange ? (
              <div
                className="mailbox-ingestion-panel border-t border-border bg-muted/10 px-3 py-3"
                data-testid={`mailbox-ingestion-section-${mb.email}`}
              >
                <MailboxIngestionRulesPanel
                  mailboxEmail={mb.email}
                  connectedMailboxEmails={connectedMailboxEmails}
                  rules={ingestionRules}
                  ruleWarnings={ingestionRuleWarnings}
                  onChange={onIngestionRulesChange}
                  canEdit={canEditIngestionRules}
                  loading={ingestionRulesLoading}
                />
              </div>
            ) : null}
          </Card>
        );
      })}
    </div>
  );
}

function MessagingChannelCard({
  brand,
  title,
  subtitle,
  providerLabel,
  lastSync,
  docCount,
  status,
  error,
  isAdmin,
  busy,
  onTest,
  onRemove,
  testIdPrefix,
}: {
  brand: "whatsapp" | "viber";
  title: string;
  subtitle: string;
  providerLabel: string;
  lastSync: string | null;
  docCount: number;
  status: string;
  error?: string | null;
  isAdmin: boolean;
  busy: boolean;
  onTest: () => void;
  onRemove: () => void;
  testIdPrefix: string;
}) {
  const connected = status === "connected";
  return (
    <Card className="p-4 min-w-0" data-testid={`card-${testIdPrefix}`}>
      <div className="flex items-start justify-between gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <IntegrationBrandIcon id={brand} size={18} />
          <div className="min-w-0">
            <p className="font-medium text-sm truncate">{title}</p>
            <p className="text-xs text-muted-foreground truncate tnum">{subtitle}</p>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex items-center rounded-md border px-2.5 py-0.5 text-[10px] font-semibold shrink-0",
            statusBadgeClass(status)
          )}
        >
          {connectionStatusLabel(status)}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-3 text-xs text-muted-foreground min-w-0">
        <span className="truncate">
          {providerLabel} · {relativeTime(lastSync)}
        </span>
        <span className="tnum shrink-0">{docCount} docs</span>
      </div>
      {error ? (
        <p className="mt-2 text-xs text-destructive line-clamp-3" title={error}>
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex items-center gap-1.5 min-w-0">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {connected ? (
            <ActionChip
              tone="post"
              icon={RefreshCw}
              label="Test"
              testId={`button-test-${testIdPrefix}`}
              disabled={busy}
              iconClassName={busy ? "animate-spin" : undefined}
              onClick={onTest}
            />
          ) : null}
        </div>
        {isAdmin && connected ? (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 text-destructive"
            data-testid={`button-remove-${testIdPrefix}`}
            onClick={onRemove}
            aria-label={`Remove ${title}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

export function UploadWhatsappChannelPanel({ docCount }: { docCount: number }) {
  const { user } = useAuth();
  const { toast } = useToast();
  const isAdmin = user?.role === "admin";
  const [connections, setConnections] = useState<WhatsappConnection[]>([]);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [connectBusy, setConnectBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const status = await api.getWhatsappStatus({ fresh: true });
      setConnections(status.connections ?? []);
      setConfigured(status.configured);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return null;

  if (connections.length === 0) {
    return (
      <Card className="p-4 mb-3 text-sm text-muted-foreground">
        No WhatsApp numbers connected yet.{" "}
        {isAdmin ? (
          <>
            <button
              type="button"
              className="text-primary hover:underline"
              disabled={connectBusy || !configured}
              onClick={async () => {
                setConnectBusy(true);
                try {
                  const { authorize_url } = await api.getWhatsappAuthorizeUrl();
                  window.location.href = authorize_url;
                } catch (e) {
                  toast({
                    title: "Could not start WhatsApp connection",
                    description: e instanceof Error ? e.message : "Connection failed",
                    variant: "destructive",
                  });
                  setConnectBusy(false);
                }
              }}
            >
              Connect WhatsApp
            </button>{" "}
            or open{" "}
            <Link to="/integrations" className="text-primary hover:underline">
              Integrations
            </Link>
            .
          </>
        ) : (
          <>
            Ask an admin to connect WhatsApp from{" "}
            <Link to="/integrations" className="text-primary hover:underline">
              Integrations
            </Link>
            .
          </>
        )}
      </Card>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-3">
      {connections.map((conn) => (
        <MessagingChannelCard
          key={conn.id}
          brand="whatsapp"
          title={conn.display_name || conn.phone_number || "WhatsApp"}
          subtitle={conn.phone_number || conn.phone_number_id}
          providerLabel="WhatsApp"
          lastSync={conn.last_sync_at}
          docCount={docCount}
          status={conn.connection_status}
          error={conn.last_error}
          isAdmin={Boolean(isAdmin)}
          busy={busyId === conn.id}
          testIdPrefix={`whatsapp-${conn.id}`}
          onTest={async () => {
            setBusyId(conn.id);
            try {
              const result = await api.testWhatsappConnection(conn.id);
              if (result.ok) {
                toast({ title: "WhatsApp test passed" });
              } else {
                toast({
                  title: "WhatsApp needs attention",
                  description: result.warnings.join(" · ") || result.integration_health,
                  variant: "destructive",
                });
              }
              await load();
            } catch (e) {
              toast({
                title: "WhatsApp test failed",
                description: e instanceof Error ? e.message : "Test failed",
                variant: "destructive",
              });
            } finally {
              setBusyId(null);
            }
          }}
          onRemove={async () => {
            setBusyId(conn.id);
            try {
              await api.disconnectWhatsapp(conn.id);
              toast({ title: "WhatsApp disconnected" });
              await load();
            } catch (e) {
              toast({
                title: "Disconnect failed",
                description: e instanceof Error ? e.message : "Could not disconnect",
                variant: "destructive",
              });
            } finally {
              setBusyId(null);
            }
          }}
        />
      ))}
    </div>
  );
}

export function UploadViberChannelPanel({ docCount }: { docCount: number }) {
  const { user } = useAuth();
  const { toast } = useToast();
  const isAdmin = user?.role === "admin";
  const [connections, setConnections] = useState<ViberConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const status = await api.getViberStatus({ fresh: true });
      setConnections(status.connections ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return null;

  if (connections.length === 0) {
    return (
      <Card className="p-4 mb-3 text-sm text-muted-foreground">
        No Viber bots connected yet.{" "}
        {isAdmin ? (
          <>
            Connect from{" "}
            <Link to="/integrations#viber-integration" className="text-primary hover:underline">
              Integrations
            </Link>
            .
          </>
        ) : (
          <>
            Ask an admin to connect Viber from{" "}
            <Link to="/integrations#viber-integration" className="text-primary hover:underline">
              Integrations
            </Link>
            .
          </>
        )}
      </Card>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-3">
      {connections.map((conn) => (
        <MessagingChannelCard
          key={conn.id}
          brand="viber"
          title="Viber Bot"
          subtitle={conn.bot_id}
          providerLabel="Viber"
          lastSync={conn.created_at}
          docCount={docCount}
          status={conn.connection_status}
          isAdmin={Boolean(isAdmin)}
          busy={busyId === conn.id}
          testIdPrefix={`viber-${conn.id}`}
          onTest={async () => {
            setBusyId(conn.id);
            try {
              const result = await api.testViberConnection(conn.id);
              if (result.ok) {
                toast({ title: "Viber test passed" });
              } else {
                toast({
                  title: "Viber needs attention",
                  description: result.integration_health,
                  variant: "destructive",
                });
              }
              await load();
            } catch (e) {
              toast({
                title: "Viber test failed",
                description: e instanceof Error ? e.message : "Test failed",
                variant: "destructive",
              });
            } finally {
              setBusyId(null);
            }
          }}
          onRemove={async () => {
            setBusyId(conn.id);
            try {
              await api.disconnectViber(conn.id);
              toast({ title: "Viber disconnected" });
              await load();
            } catch (e) {
              toast({
                title: "Disconnect failed",
                description: e instanceof Error ? e.message : "Could not disconnect",
                variant: "destructive",
              });
            } finally {
              setBusyId(null);
            }
          }}
        />
      ))}
    </div>
  );
}
