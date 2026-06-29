import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowLeftRight,
  Cloud,
  Copy,
  CreditCard,
  Database,
  FileSearch,
  Link2,
  Mail,
  MessageCircle,
  Plus,
  Server,
  Trash2,
} from "lucide-react";
import { api } from "@/api/client";
import type {
  AccountingIntegrationItem,
  AppSettings,
  ConnectedMailbox,
  MailboxConnectionRequest,
  WhatsappConnection,
} from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { useStripeAccount, useStripeReadiness } from "@/hooks/useStripe";
import { useAccountingIntegrations } from "@/hooks/useAccountingIntegrations";

function statusBadge(ok: boolean) {
  return ok ? (
    <Badge variant="outline" className="border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]">
      Connected
    </Badge>
  ) : (
    <Badge variant="secondary">Not connected</Badge>
  );
}

function comingSoonBadge() {
  return <Badge variant="secondary">Coming soon</Badge>;
}

function maskStripeAccountId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 8)}…${id.slice(-4)}`;
}

function stripeModeLabel(mode: string | undefined): string {
  const normalized = (mode || "sandbox").toLowerCase();
  if (normalized === "live") return "Live";
  return "Sandbox";
}

function accountingStatusBadge(item: AccountingIntegrationItem | undefined) {
  const status = item?.status ?? "disconnected";
  if (status === "connected") {
    return (
      <Badge variant="outline" className="border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]">
        Connected
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge variant="outline" className="border-destructive/40 text-destructive">
        Error
      </Badge>
    );
  }
  if (status === "expired") {
    return <Badge variant="secondary">Expired</Badge>;
  }
  return <Badge variant="secondary">Not connected</Badge>;
}

function accountingConnected(item: AccountingIntegrationItem | undefined): boolean {
  return item?.status === "connected";
}

function accountingTagline(
  item: AccountingIntegrationItem | undefined,
  fallback: string
): string {
  if (!item || item.status === "disconnected") return fallback;
  if (item.display_name) return item.display_name;
  if (item.status === "error") {
    return item.last_error || "Connection error — try reconnecting";
  }
  if (item.status === "expired") return "Session expired — reconnect to continue";
  return fallback;
}

const ACCOUNTING_OAUTH_ERRORS: Record<string, string> = {
  not_configured: "Accounting credentials are not configured on the server.",
  invalid_state: "Connection session expired — try Connect again.",
  not_admin: "Only tenant admins can connect accounting integrations.",
  oauth_failed: "OAuth connection failed or was cancelled.",
  missing_code: "Authorization code missing from provider callback.",
  missing_realm: "QuickBooks company id missing from callback.",
};

function requestStatusLabel(status: string) {
  if (status === "pending") return "Pending";
  if (status === "connected") return "Connected";
  if (status === "expired") return "Expired";
  return status;
}

export function IntegrationsPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [s, setS] = useState<AppSettings | null>(null);
  const [mailboxes, setMailboxes] = useState<ConnectedMailbox[]>([]);
  const [requests, setRequests] = useState<MailboxConnectionRequest[]>([]);
  const [mbError, setMbError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteMessage, setInviteMessage] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [lastInviteLink, setLastInviteLink] = useState<string | null>(null);
  const [adminConsentUrl, setAdminConsentUrl] = useState<string | null>(null);
  const [adminConsentNote, setAdminConsentNote] = useState<string | null>(null);
  const [waConnections, setWaConnections] = useState<WhatsappConnection[]>([]);
  const [waWebhookUrl, setWaWebhookUrl] = useState<string>("");
  const [waOAuthUrl, setWaOAuthUrl] = useState<string>("");
  const [waError, setWaError] = useState<string | null>(null);
  const [waBusy, setWaBusy] = useState(false);
  const [accountingBusy, setAccountingBusy] = useState<string | null>(null);
  const [accountingError, setAccountingError] = useState<string | null>(null);
  const {
    status: accountingStatus,
    loading: accountingLoading,
    reload: reloadAccounting,
  } = useAccountingIntegrations(Boolean(s));
  const { data: stripeAccount, isLoading: stripeAccountLoading } = useStripeAccount(Boolean(s));
  const { data: stripeReadiness, isLoading: stripeReadinessLoading } = useStripeReadiness(Boolean(s));

  async function copyInviteLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast({ title: "Invite link copied" });
    } catch {
      toast({ title: "Could not copy link", variant: "destructive" });
    }
  }

  const loadMailboxes = useCallback((fresh = false) => {
    api.listMailboxes({ fresh }).then(setMailboxes).catch(() => setMailboxes([]));
  }, []);

  const loadRequests = useCallback((fresh = false) => {
    api
      .listMailboxConnectionRequests({ fresh })
      .then(setRequests)
      .catch(() => setRequests([]));
  }, []);

  const loadWhatsapp = useCallback((fresh = false) => {
    api
      .getWhatsappStatus({ fresh })
      .then((status) => {
        setWaConnections(status.connections);
        setWaWebhookUrl(status.webhook_callback_url);
        setWaOAuthUrl(status.oauth_callback_url);
        setWaError(null);
      })
      .catch(() => {
        setWaConnections([]);
        setWaWebhookUrl("");
      });
  }, []);

  useEffect(() => {
    api.getSettings().then(setS);
    loadMailboxes();
    loadRequests();
    loadWhatsapp();
  }, [loadMailboxes, loadRequests, loadWhatsapp]);

  useEffect(() => {
    if (user?.role !== "admin") return;
    api
      .getMailboxAdminConsentUrl()
      .then((data) => {
        setAdminConsentUrl(data.admin_consent_url);
        setAdminConsentNote(data.instructions);
      })
      .catch(() => {
        setAdminConsentUrl(null);
        setAdminConsentNote(null);
      });
  }, [user?.role]);

  useEffect(() => {
    const oauth = searchParams.get("mailbox_oauth");
    if (!oauth) return;
    const email = searchParams.get("email");
    const message = searchParams.get("message");
    if (oauth === "success") {
      toast({
        title: "Mailbox connected",
        description: email ? `${email} is authorized for invoice capture.` : undefined,
      });
      loadMailboxes(true);
      loadRequests(true);
    } else if (oauth === "error") {
      setMbError(message || "Microsoft sign-in was cancelled or failed");
    }
    searchParams.delete("mailbox_oauth");
    searchParams.delete("email");
    searchParams.delete("message");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams, toast, loadMailboxes, loadRequests]);

  useEffect(() => {
    const wa = searchParams.get("wa");
    if (!wa) return;
    const phone = searchParams.get("phone");
    const reason = searchParams.get("reason");
    if (wa === "connected") {
      toast({
        title: "WhatsApp connected",
        description: phone ? `${phone} is ready for expense capture.` : undefined,
      });
      loadWhatsapp(true);
    } else if (wa === "error") {
      const messages: Record<string, string> = {
        no_waba: "No WhatsApp Business Account found on this Meta login.",
        no_phone: "No phone numbers found on your WhatsApp Business Account.",
        invalid_state: "Connection session expired or invalid — try Connect again.",
        not_admin: "Only admins can connect WhatsApp.",
        not_configured: "Meta app credentials are missing on the server.",
        oauth_failed: "Facebook login failed or was cancelled.",
      };
      const msg = messages[reason ?? ""] ?? reason ?? "WhatsApp connection failed";
      setWaError(msg);
      toast({
        title: "WhatsApp connection failed",
        description: msg,
        variant: "destructive",
      });
    }
    searchParams.delete("wa");
    searchParams.delete("phone");
    searchParams.delete("reason");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams, toast, loadWhatsapp]);

  useEffect(() => {
    const xero = searchParams.get("xero");
    if (!xero) return;
    const company = searchParams.get("company");
    const reason = searchParams.get("reason");
    if (xero === "connected") {
      toast({
        title: "Xero connected",
        description: company ? `${company} is linked to this tenant.` : undefined,
      });
      void reloadAccounting(true);
    } else if (xero === "error") {
      const msg = ACCOUNTING_OAUTH_ERRORS[reason ?? ""] ?? reason ?? "Xero connection failed";
      setAccountingError(msg);
      toast({ title: "Xero connection failed", description: msg, variant: "destructive" });
      void reloadAccounting(true);
    }
    searchParams.delete("xero");
    searchParams.delete("company");
    searchParams.delete("reason");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams, toast, reloadAccounting]);

  useEffect(() => {
    const quickbooks = searchParams.get("quickbooks");
    if (!quickbooks) return;
    const company = searchParams.get("company");
    const reason = searchParams.get("reason");
    if (quickbooks === "connected") {
      toast({
        title: "QuickBooks connected",
        description: company ? `${company} is linked to this tenant.` : undefined,
      });
      void reloadAccounting(true);
    } else if (quickbooks === "error") {
      const msg =
        ACCOUNTING_OAUTH_ERRORS[reason ?? ""] ?? reason ?? "QuickBooks connection failed";
      setAccountingError(msg);
      toast({
        title: "QuickBooks connection failed",
        description: msg,
        variant: "destructive",
      });
      void reloadAccounting(true);
    }
    searchParams.delete("quickbooks");
    searchParams.delete("company");
    searchParams.delete("reason");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams, toast, reloadAccounting]);

  async function startAccountingConnect(provider: "xero" | "quickbooks_online") {
    setAccountingBusy(provider);
    setAccountingError(null);
    try {
      const { connect_url } =
        provider === "xero" ? await api.connectXero() : await api.connectQuickBooks();
      window.location.href = connect_url;
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Could not start OAuth");
      setAccountingBusy(null);
    }
  }

  async function disconnectAccounting(provider: "xero" | "quickbooks_online") {
    setAccountingBusy(provider);
    setAccountingError(null);
    try {
      await api.disconnectAccountingIntegration(provider);
      await reloadAccounting(true);
      toast({
        title: provider === "xero" ? "Xero disconnected" : "QuickBooks disconnected",
      });
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Disconnect failed");
    } finally {
      setAccountingBusy(null);
    }
  }

  function accountingCardFooter(
    provider: "xero" | "quickbooks_online",
    item: AccountingIntegrationItem | undefined,
    configured: boolean
  ) {
    if (user?.role !== "admin") return null;
    if (!configured) {
      return (
        <p className="text-[11px] text-muted-foreground mt-1.5">
          Set provider OAuth credentials in backend environment (see docs).
        </p>
      );
    }
    const connected = accountingConnected(item);
    return (
      <div className="mt-1.5">
        <Button
          size="sm"
          variant={connected ? "outline" : "default"}
          className="h-7 text-xs"
          disabled={accountingBusy === provider || accountingLoading}
          onClick={() =>
            void (connected ? disconnectAccounting(provider) : startAccountingConnect(provider))
          }
        >
          {accountingBusy === provider
            ? connected
              ? "Disconnecting…"
              : "Redirecting…"
            : connected
              ? "Disconnect"
              : "Connect"}
        </Button>
      </div>
    );
  }

  async function sendInvitation(e: React.FormEvent) {
    e.preventDefault();
    setMbError(null);
    setInviteBusy(true);
    try {
      const result = await api.createMailboxConnectionRequest({
        email: inviteEmail.trim(),
        display_name: inviteName.trim() || undefined,
        message: inviteMessage.trim() || undefined,
      });
      setLastInviteLink(result.connect_url);
      if (result.email_sent) {
        toast({
          title: "Invitation sent",
          description: `${inviteEmail.trim()} will receive an email to connect their mailbox.`,
        });
      } else {
        toast({
          title: "Invitation created",
          description:
            result.email_error ??
            "Email could not be sent. Copy the invite link below and share it manually.",
        });
        if (result.email_error) {
          setMbError(result.email_error);
        }
      }
      setInviteEmail("");
      setInviteName("");
      setInviteMessage("");
      loadRequests(true);
    } catch (err) {
      setMbError(err instanceof Error ? err.message : "Failed to send invitation");
    } finally {
      setInviteBusy(false);
    }
  }

  const stripePaymentsConnected =
    stripeReadiness?.connected === true ||
    (stripeAccount != null && stripeAccount.onboarding_status !== "disconnected");

  const stripePaymentsTagline = useMemo(() => {
    if (stripeAccountLoading || stripeReadinessLoading) {
      return "Loading Stripe Connect status…";
    }
    if (!stripePaymentsConnected) {
      return "Payables disbursement & balance visibility — connect on Payments";
    }
    const mode = stripeModeLabel(s?.stripe_mode);
    const accountId =
      stripeReadiness?.account_id ??
      stripeAccount?.stripe_account_id ??
      null;
    const masked = accountId ? maskStripeAccountId(accountId) : "account linked";
    if (stripeReadiness?.ready_for_charges && stripeReadiness.ready_for_payouts) {
      return `${mode} · ${masked} · Ready for charges & payouts`;
    }
    if (stripeReadiness?.blocking_reason) {
      return `${mode} · ${masked} · ${stripeReadiness.blocking_reason}`;
    }
    return `${mode} · ${masked}`;
  }, [
    s?.stripe_mode,
    stripeAccount,
    stripeAccountLoading,
    stripePaymentsConnected,
    stripeReadiness,
    stripeReadinessLoading,
  ]);

  const xeroItem = accountingStatus?.xero;
  const qboItem = accountingStatus?.quickbooks_online;

  const items = useMemo(
    () => {
      if (!s) return [];
      return [
    {
      id: "graph",
      name: "Microsoft Graph",
      tagline: s.graph_mailbox || "Outlook capture",
      ok: s.graph_enabled,
      icon: Mail,
    },
    {
      id: "whatsapp",
      name: "WhatsApp Business",
      tagline: waConnections[0]?.phone_number || "Team expense capture",
      ok: s.whatsapp_configured && waConnections.some((c) => c.connection_status === "connected"),
      icon: MessageCircle,
    },
    {
      id: "blob",
      name: "Azure Blob Storage",
      tagline: s.azure_storage_container,
      ok: s.blob_enabled,
      icon: Cloud,
    },
    {
      id: "di",
      name: "Azure Document Intelligence",
      tagline: "Invoice OCR & extraction",
      ok: s.azure_di_enabled,
      icon: FileSearch,
    },
    {
      id: "postgres",
      name: "Azure PostgreSQL",
      tagline: s.azure_location ? `${s.azure_location} flexible server` : "Managed database",
      ok: s.azure_postgres_enabled,
      icon: Database,
    },
    {
      id: "redis",
      name: "Azure Redis",
      tagline: "Celery broker & task queue",
      ok: s.azure_redis_enabled,
      icon: Server,
    },
    {
      id: "appinsights",
      name: "Application Insights",
      tagline: "Telemetry & monitoring",
      ok: s.appinsights_enabled,
      icon: Activity,
    },
    {
      id: "xero",
      name: "Xero",
      tagline: accountingTagline(xeroItem, "Chart of accounts & journals"),
      ok: accountingConnected(xeroItem),
      icon: ArrowLeftRight,
      badge: accountingStatusBadge(xeroItem),
      footer: accountingCardFooter("xero", xeroItem, s.xero_configured),
    },
    {
      id: "qbo",
      name: "QuickBooks Online",
      tagline: accountingTagline(qboItem, "Bills & journals"),
      ok: accountingConnected(qboItem),
      icon: ArrowLeftRight,
      badge: accountingStatusBadge(qboItem),
      footer: accountingCardFooter("quickbooks_online", qboItem, s.quickbooks_configured),
    },
    {
      id: "myob",
      name: "MYOB",
      tagline: "Purchase entries (coming soon)",
      ok: false,
      icon: ArrowLeftRight,
    },
    {
      id: "stripe-payments",
      name: "Stripe Payments / Connect",
      tagline: stripePaymentsTagline,
      ok: stripePaymentsConnected,
      icon: CreditCard,
      badge: statusBadge(stripePaymentsConnected),
      footer: stripePaymentsConnected ? (
        <Link
          to="/payments"
          className="text-[11px] text-primary hover:underline"
        >
          Manage on Payments
        </Link>
      ) : (
        <Link
          to="/payments"
          className="text-[11px] text-primary hover:underline"
        >
          Connect on Payments
        </Link>
      ),
    },
    {
      id: "stripe-billing",
      name: "Stripe Billing / Credits",
      tagline: "Credit pack billing for LedgerLink usage (not enabled)",
      ok: false,
      icon: ArrowLeftRight,
      badge: comingSoonBadge(),
    },
  ];
    },
    [
      s,
      waConnections,
      xeroItem,
      qboItem,
      stripePaymentsTagline,
      stripePaymentsConnected,
      accountingBusy,
      accountingLoading,
      user?.role,
    ]
  );

  if (!s) {
    return <p className="text-sm text-muted-foreground">Loading integrations…</p>;
  }

  const connected = items.filter((i) => i.ok).length;
  const pendingRequests = requests.filter((r) => r.status === "pending");

  return (
    <div>
      <PageHeader
        title="Integrations"
        subtitle={`${connected} of ${items.length} services connected`}
      />

      {accountingError && (
        <p className="text-sm text-destructive mb-4">{accountingError}</p>
      )}

      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3 mb-6">
        {items.map((h) => (
          <Card
            key={h.id}
            className="p-4 flex flex-col gap-3"
            data-testid={`card-integration-${h.id}`}
          >
            <div className="flex items-start justify-between">
              <div className="h-10 w-10 rounded-md bg-muted flex items-center justify-center text-primary">
                <h.icon className="h-5 w-5" />
              </div>
              {"badge" in h && h.badge ? h.badge : statusBadge(h.ok)}
            </div>
            <div>
              <p className="text-sm font-medium">{h.name}</p>
              <p className="text-xs text-muted-foreground">{h.tagline}</p>
              {"footer" in h && h.footer ? <div className="mt-1.5">{h.footer}</div> : null}
            </div>
          </Card>
        ))}
      </div>

      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Mailbox connection requests</h2>
            <p className="text-xs text-muted-foreground">
              Send an invitation email, or copy the link and share it in Teams. The mailbox
              owner opens the link and completes Microsoft consent — no shared passwords.
            </p>
          </div>
          <Mail className="h-5 w-5 text-muted-foreground" />
        </div>

        {user?.role === "admin" && (
          <form onSubmit={(e) => void sendInvitation(e)} className="grid gap-3 mb-4 max-w-xl">
            <Input
              type="email"
              required
              placeholder="Mailbox email (e.g. finance@company.com)"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
            <Input
              placeholder="Display name (optional)"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
            />
            <Input
              placeholder="Message to recipient (optional)"
              value={inviteMessage}
              onChange={(e) => setInviteMessage(e.target.value)}
            />
            <div>
              <Button type="submit" size="sm" disabled={inviteBusy}>
                <Plus className="h-4 w-4 mr-1" />
                {inviteBusy ? "Sending…" : "Send invitation"}
              </Button>
            </div>
          </form>
        )}

        {mbError && <p className="text-sm text-destructive mb-2">{mbError}</p>}

        {user?.role === "admin" && adminConsentUrl && (
          <div className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 space-y-2 max-w-2xl">
            <p className="text-xs font-medium text-foreground">
              Users see &quot;Need admin approval&quot;?
            </p>
            <p className="text-xs text-muted-foreground">
              {adminConsentNote ??
                "A Microsoft 365 Global Administrator must grant org-wide consent once."}
            </p>
            <div className="flex flex-wrap gap-2">
              <a
                href={adminConsentUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-8 items-center justify-center rounded-md border border-input bg-background px-3 text-xs font-medium hover:bg-accent hover:text-accent-foreground"
              >
                Open Microsoft admin consent
              </a>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => void copyInviteLink(adminConsentUrl)}
              >
                <Copy className="h-4 w-4 mr-1" />
                Copy consent link
              </Button>
            </div>
          </div>
        )}

        {lastInviteLink && (
          <div className="mb-4 rounded-md border border-border bg-muted/40 p-3 space-y-2 max-w-xl">
            <p className="text-xs text-muted-foreground">
              Share this link with the mailbox owner if email delivery is unavailable:
            </p>
            <div className="flex gap-2">
              <Input readOnly value={lastInviteLink} className="text-xs font-mono" />
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => void copyInviteLink(lastInviteLink)}
              >
                <Copy className="h-4 w-4 mr-1" />
                Copy
              </Button>
            </div>
          </div>
        )}

        {pendingRequests.length === 0 && requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">No connection requests yet.</p>
        ) : (
          <ul className="space-y-2">
            {requests.map((req) => (
              <li
                key={req.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm gap-3"
              >
                <div className="min-w-0">
                  <span className="font-medium">{req.requested_email}</span>
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    {requestStatusLabel(req.status)}
                  </Badge>
                  {req.invite_sent_at && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Sent {new Date(req.invite_sent_at).toLocaleString()}
                    </p>
                  )}
                </div>
                {user?.role === "admin" && req.status === "pending" && (
                  <div className="flex gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
                        try {
                          const { connect_url } = await api.getMailboxConnectionInviteLink(req.id);
                          await copyInviteLink(connect_url);
                          setLastInviteLink(connect_url);
                          setMbError(null);
                        } catch (e) {
                          setMbError(e instanceof Error ? e.message : "Could not get invite link");
                        }
                      }}
                    >
                      <Link2 className="h-3.5 w-3.5 mr-1" />
                      Copy link
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
                        try {
                          const result = await api.resendMailboxConnectionRequest(req.id);
                          setLastInviteLink(result.connect_url);
                          if (result.email_sent) {
                            toast({ title: "Invitation resent" });
                            setMbError(null);
                          } else {
                            toast({
                              title: "Link refreshed",
                              description:
                                result.email_error ??
                                "Email could not be sent. Copy the invite link and share manually.",
                            });
                            setMbError(result.email_error ?? null);
                          }
                          loadRequests(true);
                        } catch (e) {
                          setMbError(e instanceof Error ? e.message : "Resend failed");
                        }
                      }}
                    >
                      Resend
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Connected mailboxes</h2>
            <p className="text-xs text-muted-foreground">
              Mailboxes authorized for invoice capture via OAuth.
            </p>
          </div>
        </div>
        {mailboxes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No mailboxes connected yet. Send an invitation above, or set GRAPH_MAILBOX in
            backend .env for legacy application-permission polling.
          </p>
        ) : (
          <ul className="space-y-2">
            {mailboxes.map((mb) => (
              <li
                key={mb.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-medium">{mb.email}</span>
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    {mb.auth_type === "delegated" ? "OAuth" : "App"}
                  </Badge>
                  {mb.connection_status !== "connected" && (
                    <Badge variant="secondary" className="ml-2 text-[10px]">
                      {mb.connection_status}
                    </Badge>
                  )}
                  {!mb.is_active && (
                    <Badge variant="secondary" className="ml-2 text-[10px]">
                      Paused
                    </Badge>
                  )}
                  {mb.last_error && (
                    <p className="text-xs text-destructive mt-1">{mb.last_error}</p>
                  )}
                </div>
                {user?.role === "admin" && (
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
                        try {
                          const updated = await api.toggleMailbox(mb.id);
                          setMailboxes((prev) =>
                            prev.map((m) => (m.id === updated.id ? updated : m))
                          );
                          setMbError(null);
                        } catch (e) {
                          setMbError(e instanceof Error ? e.message : "Failed to update mailbox");
                        }
                      }}
                    >
                      {mb.is_active ? "Pause" : "Resume"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      onClick={async () => {
                        try {
                          await api.removeMailbox(mb.id);
                          loadMailboxes(true);
                          setMbError(null);
                        } catch (e) {
                          setMbError(e instanceof Error ? e.message : "Failed to remove mailbox");
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">WhatsApp Business</h2>
            <p className="text-xs text-muted-foreground">
              Connect a business number so employees can submit expense receipts via WhatsApp.
              Identity is matched by phone number in Rule Book → Employees.
            </p>
          </div>
          <MessageCircle className="h-5 w-5 text-muted-foreground" />
        </div>

        {waError && <p className="text-sm text-destructive mb-2">{waError}</p>}

        {waOAuthUrl && (
          <div className="mb-4 rounded-md border border-border bg-muted/40 p-3 space-y-2 max-w-2xl">
            <p className="text-xs text-muted-foreground">
              Facebook Login OAuth redirect URI (Meta app → Facebook Login → Valid OAuth Redirect
              URIs):
            </p>
            <div className="flex gap-2">
              <Input readOnly value={waOAuthUrl} className="text-xs font-mono" />
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => void copyInviteLink(waOAuthUrl)}
              >
                <Copy className="h-4 w-4 mr-1" />
                Copy
              </Button>
            </div>
          </div>
        )}

        {waWebhookUrl && (
          <div className="mb-4 rounded-md border border-border bg-muted/40 p-3 space-y-2 max-w-2xl">
            <p className="text-xs text-muted-foreground">
              Meta webhook callback URL (register in Meta Developer Console → WhatsApp →
              Configuration):
            </p>
            <div className="flex gap-2">
              <Input readOnly value={waWebhookUrl} className="text-xs font-mono" />
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => void copyInviteLink(waWebhookUrl)}
              >
                <Copy className="h-4 w-4 mr-1" />
                Copy
              </Button>
            </div>
          </div>
        )}

        {user?.role === "admin" && (
          <div className="mb-4">
            <Button
              size="sm"
              disabled={waBusy || !s.whatsapp_configured}
              onClick={async () => {
                setWaBusy(true);
                setWaError(null);
                try {
                  const { authorize_url } = await api.getWhatsappAuthorizeUrl();
                  window.location.href = authorize_url;
                } catch (e) {
                  setWaError(e instanceof Error ? e.message : "Could not start Facebook login");
                  setWaBusy(false);
                }
              }}
            >
              {waBusy ? "Redirecting…" : "Connect WhatsApp Business"}
            </Button>
            {!s.whatsapp_configured && (
              <p className="text-xs text-muted-foreground mt-2">
                Set META_APP_ID, META_APP_SECRET, and META_WEBHOOK_VERIFY_TOKEN in backend .env.
              </p>
            )}
          </div>
        )}

        {waConnections.length === 0 ? (
          <p className="text-sm text-muted-foreground">No WhatsApp numbers connected yet.</p>
        ) : (
          <ul className="space-y-2">
            {waConnections.map((conn) => (
              <li
                key={conn.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm gap-3"
              >
                <div className="min-w-0">
                  <span className="font-medium">
                    {conn.display_name || conn.phone_number || conn.phone_number_id}
                  </span>
                  {conn.phone_number && (
                    <span className="text-muted-foreground ml-2">{conn.phone_number}</span>
                  )}
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    {conn.integration_health}
                  </Badge>
                  {conn.last_error && (
                    <p className="text-xs text-destructive mt-1">{conn.last_error}</p>
                  )}
                </div>
                {user?.role === "admin" && (
                  <div className="flex gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
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
                          loadWhatsapp(true);
                        } catch (e) {
                          setWaError(e instanceof Error ? e.message : "Test failed");
                        }
                      }}
                    >
                      Test
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      onClick={async () => {
                        try {
                          await api.disconnectWhatsapp(conn.id);
                          loadWhatsapp(true);
                          toast({ title: "WhatsApp disconnected" });
                        } catch (e) {
                          setWaError(e instanceof Error ? e.message : "Disconnect failed");
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="text-sm font-semibold mb-1">Planned Xero & QuickBooks sync</h2>
        <p className="text-xs text-muted-foreground mb-4">
          OAuth connection is live; bill and journal sync is not enabled yet. Planned features:
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {["Chart of accounts", "Contacts", "Bills & payments", "Tax rates", "Tracking categories"].map(
            (h) => (
              <div
                key={h}
                className="flex items-center gap-3 rounded-md border border-border p-3"
              >
                <span className="text-[11px] font-semibold text-primary">Ledgerline</span>
                <ArrowLeftRight className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-[11px] font-semibold text-muted-foreground">Xero</span>
                <span className="text-sm ml-auto">{h}</span>
              </div>
            )
          )}
        </div>
      </Card>
    </div>
  );
}
