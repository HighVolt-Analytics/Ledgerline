import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Calendar, Mail, Pause, Play, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import type { ConnectedMailbox, ViberConnection, WhatsappConnection } from "@/api/types";
import { ActionChip } from "@/components/ActionChip";
import { IntegrationBrandIcon } from "@/components/integrations/IntegrationBrandIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { cn } from "@/lib/cn";
import { mailboxDisplayName } from "@/lib/invoice";

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
}: EmailPanelProps) {
  if (mailboxes.length === 0) {
    if (loading) return null;
    return (
      <Card className="p-4 mb-5 text-sm text-muted-foreground">
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
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-5">
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
                  statusBadgeClass(mb.connection_status, mb.is_active)
                )}
              >
                {connectionStatusLabel(mb.connection_status, mb.is_active)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2 mt-3 text-xs text-muted-foreground min-w-0">
              <span className="truncate">
                {mailboxProvider(mb)} · {relativeTime(mb.last_poll_at)}
              </span>
              <span className="tnum shrink-0">{docCount} docs</span>
            </div>
            {mb.connection_status === "error" && mb.last_error ? (
              <p className="mt-2 text-xs text-destructive line-clamp-3" title={mb.last_error}>
                {mb.last_error}
              </p>
            ) : null}
            <div className="mt-3 flex items-center gap-1.5 min-w-0">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                {mb.connection_status === "error" && isAdmin ? (
                  <ActionChip
                    tone="approve"
                    icon={Mail}
                    label="Reconnect"
                    testId={`button-reconnect-${mb.email}`}
                    disabled={importBusy || fetching === mb.email}
                    onClick={() => onReconnect(mb)}
                  />
                ) : null}
                <ActionChip
                  tone="edit"
                  icon={Calendar}
                  label="Import"
                  testId={`button-import-${mb.email}`}
                  disabled={importBusy || fetching === mb.email || !isPollable(mb)}
                  onClick={() => onImport(mb)}
                />
                <ActionChip
                  tone="post"
                  icon={RefreshCw}
                  label="Fetch"
                  testId={`button-fetch-${mb.email}`}
                  disabled={fetching === mb.email || importBusy || !isPollable(mb)}
                  iconClassName={fetching === mb.email ? "animate-spin" : undefined}
                  onClick={() => onFetch(mb)}
                />
                {isAdmin ? (
                  <ActionChip
                    tone={mb.is_active ? "pending" : "approve"}
                    icon={mb.is_active ? Pause : Play}
                    label={mb.is_active ? "Pause" : "Resume"}
                    testId={`button-toggle-${mb.email}`}
                    onClick={() => onToggle(mb)}
                  />
                ) : null}
              </div>
              {isAdmin ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0 text-destructive"
                  data-testid={`button-remove-${mb.email}`}
                  onClick={() => onRemove(mb)}
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
      <Card className="p-4 mb-5 text-sm text-muted-foreground">
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
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-5">
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
      <Card className="p-4 mb-5 text-sm text-muted-foreground">
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
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-5">
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
