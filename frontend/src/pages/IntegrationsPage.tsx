import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
  Sparkles,
  Trash2,
} from "lucide-react";
import { api } from "@/api/client";
import type {
  AccountingIntegrationItem,
  AppSettings,
  ConnectedMailbox,
  MailboxConnectionRequest,
  ViberConnection,
  WhatsappConnection,
  XeroReadiness,
} from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
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

function xeroReadinessBadge(readiness: XeroReadiness | null | undefined) {
  const status = readiness?.status ?? "disconnected";
  if (readiness?.ready) {
    return (
      <Badge variant="outline" className="border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]">
        Ready
      </Badge>
    );
  }
  if (status === "organisation_selection_required") {
    return <Badge variant="secondary">Select organisation</Badge>;
  }
  if (status === "needs_reauth") {
    return (
      <Badge variant="outline" className="border-amber-500/40 text-amber-700 dark:text-amber-400">
        Reconnect required
      </Badge>
    );
  }
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

function xeroStateLabel(readiness: XeroReadiness | null | undefined): string {
  if (!readiness?.configured) return "Not configured on server";
  if (!readiness.connected) return "Not connected";
  if (readiness.ready) {
    return readiness.display_name
      ? `${readiness.display_name} · Ready for sync & push`
      : "Ready for sync & push";
  }
  if (readiness.status === "organisation_selection_required") {
    return "Choose which Xero organisation to link";
  }
  if (readiness.status === "needs_reauth") {
    return readiness.last_error || "Session expired — reconnect Xero";
  }
  if (readiness.status === "error") {
    return readiness.last_error || "Connection error — try reconnecting";
  }
  if (readiness.display_name) return readiness.display_name;
  return "Connected — finishing setup";
}

function needsXeroOrgSelection(readiness: XeroReadiness | null | undefined): boolean {
  return (
    readiness?.status === "organisation_selection_required" ||
    (readiness?.connected === true && readiness.organisation_selected === false)
  );
}

const XERO_OAUTH_SELECT_ORG = new Set(["organisation_selection_required", "select_org"]);

function accountingConnected(item: AccountingIntegrationItem | undefined): boolean {
  return item?.status === "connected" || item?.status === "organisation_selection_required";
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

function globalPayoutsAccessLabel(status: string | undefined): string {
  const normalized = (status || "not_requested").toLowerCase();
  if (normalized === "pending_approval") return "Pending approval";
  if (normalized === "enabled") return "Enabled";
  if (normalized === "rejected") return "Rejected";
  return "Not requested";
}

function requestStatusLabel(status: string) {
  if (status === "pending") return "Pending";
  if (status === "connected") return "Connected";
  if (status === "expired") return "Expired";
  return status;
}

export function IntegrationsPage() {
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const loadSeq = useRef(0);
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
  const [xeroSyncBusy, setXeroSyncBusy] = useState<"settings" | "contacts" | "select" | "verify" | null>(null);
  const [showXeroOrgPicker, setShowXeroOrgPicker] = useState(false);
  const {
    status: accountingStatus,
    xeroReadiness,
    xeroVerify,
    xeroConnections,
    loading: accountingLoading,
    xeroLoading,
    xeroError,
    reload: reloadAccounting,
    reloadAll: reloadAccountingAll,
    selectXeroOrg,
    syncXeroSettings,
    syncXeroContacts,
    verifyXeroConnection,
  } = useAccountingIntegrations(Boolean(s));
  const { data: stripeAccount, isLoading: stripeAccountLoading } = useStripeAccount(Boolean(s));
  const { data: stripeReadiness, isLoading: stripeReadinessLoading } = useStripeReadiness(Boolean(s));
  const [vbConnections, setVbConnections] = useState<ViberConnection[]>([]);
  const [vbWebhookUrl, setVbWebhookUrl] = useState<string>("");
  const [vbWebhookReachable, setVbWebhookReachable] = useState<boolean | null>(null);
  const [vbWebhookHint, setVbWebhookHint] = useState<string | null>(null);
  const [vbError, setVbError] = useState<string | null>(null);
  const [vbBusy, setVbBusy] = useState(false);
  const [vbAuthToken, setVbAuthToken] = useState("");

  const scopeOk = canRenderTenantOwnedUi(tenantScope);
  const visibleMailboxes = scopeOk ? mailboxes : [];

  useResetOnTenantChange(() => {
    setS(null);
    setMailboxes([]);
    setRequests([]);
    setMbError(null);
    setInviteEmail("");
    setInviteName("");
    setInviteMessage("");
    setLastInviteLink(null);
    setWaConnections([]);
    setWaWebhookUrl("");
    setWaOAuthUrl("");
    setWaError(null);
    setVbConnections([]);
    setVbWebhookUrl("");
    setVbWebhookReachable(null);
    setVbWebhookHint(null);
    setVbError(null);
    setAdminConsentUrl(null);
    setAdminConsentNote(null);
    setShowXeroOrgPicker(false);
    setXeroSyncBusy(null);
  });

  const loadMailboxes = useCallback((fresh = false) => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const scope = captureTenantFetchScope();
    const seq = loadSeq.current;
    api.listMailboxes({ fresh }).then((rows) => {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setMailboxes(rows);
    }).catch(() => {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setMailboxes([]);
    });
  }, [tenantScope]);

  const loadRequests = useCallback((fresh = false) => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const scope = captureTenantFetchScope();
    const seq = loadSeq.current;
    api
      .listMailboxConnectionRequests({ fresh })
      .then((rows) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setRequests(rows);
      })
      .catch(() => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setRequests([]);
      });
  }, [tenantScope]);

  const loadWhatsapp = useCallback((fresh = false) => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const scope = captureTenantFetchScope();
    const seq = loadSeq.current;
    api
      .getWhatsappStatus({ fresh })
      .then((status) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setWaConnections(status.connections);
        setWaWebhookUrl(status.webhook_callback_url);
        setWaOAuthUrl(status.oauth_callback_url);
        setWaError(null);
      })
      .catch(() => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setWaConnections([]);
        setWaWebhookUrl("");
      });
  }, [tenantScope]);

  const loadViber = useCallback((fresh = false) => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const scope = captureTenantFetchScope();
    const seq = loadSeq.current;
    api
      .getViberStatus({ fresh })
      .then((status) => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setVbConnections(status.connections);
        setVbWebhookUrl(status.webhook_callback_url);
        setVbWebhookReachable(status.webhook_reachable);
        setVbWebhookHint(status.webhook_reachability_hint ?? null);
        setVbError(null);
      })
      .catch(() => {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setVbConnections([]);
        setVbWebhookUrl("");
        setVbWebhookReachable(null);
        setVbWebhookHint(null);
      });
  }, [tenantScope]);

  useLayoutEffect(() => {
    loadSeq.current += 1;
  }, [tenantScope]);

  useEffect(() => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const scope = captureTenantFetchScope();
    const seq = loadSeq.current;
    api.getSettings().then((settings) => {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setS(settings);
    });
    loadMailboxes();
    loadRequests();
    loadWhatsapp();
    loadViber();
  }, [loadMailboxes, loadRequests, loadWhatsapp, loadViber, tenantScope]);

  async function copyInviteLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast({ title: "Invite link copied" });
    } catch {
      toast({ title: "Could not copy link", variant: "destructive" });
    }
  }

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
      void reloadAccountingAll(true);
    } else if (XERO_OAUTH_SELECT_ORG.has(xero)) {
      setShowXeroOrgPicker(true);
      toast({
        title: "Select Xero organisation",
        description: "Choose which Xero organisation to connect to this tenant.",
      });
      void reloadAccountingAll(true);
    } else if (xero === "error") {
      const msg = ACCOUNTING_OAUTH_ERRORS[reason ?? ""] ?? reason ?? "Xero connection failed";
      setAccountingError(msg);
      toast({ title: "Xero connection failed", description: msg, variant: "destructive" });
      void reloadAccountingAll(true);
    }
    searchParams.delete("xero");
    searchParams.delete("company");
    searchParams.delete("reason");
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams, toast, reloadAccountingAll]);

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
    const label = provider === "xero" ? "Xero" : "QuickBooks";
    if (
      !window.confirm(
        `Disconnect ${label} from this organisation? Synced references remain, but live push and sync will stop.`
      )
    ) {
      return;
    }
    setAccountingBusy(provider);
    setAccountingError(null);
    try {
      await api.disconnectAccountingIntegration(provider);
      await reloadAccountingAll(true);
      setShowXeroOrgPicker(false);
      toast({
        title: provider === "xero" ? "Xero disconnected" : "QuickBooks disconnected",
      });
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Disconnect failed");
    } finally {
      setAccountingBusy(null);
    }
  }

  async function handleSelectXeroOrg(xeroConnectionId: string) {
    setXeroSyncBusy("select");
    setAccountingError(null);
    try {
      const result = await selectXeroOrg(xeroConnectionId);
      setShowXeroOrgPicker(false);
      toast({
        title: "Xero organisation selected",
        description: result.display_name ?? undefined,
      });
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Could not select organisation");
    } finally {
      setXeroSyncBusy(null);
    }
  }

  async function handleSyncXeroSettings() {
    setXeroSyncBusy("settings");
    setAccountingError(null);
    try {
      const result = await syncXeroSettings();
      toast({
        title: "Xero settings synced",
        description: `${result.account} accounts · ${result.tax_rate} tax rates · ${result.currency} currencies`,
      });
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Settings sync failed");
      toast({
        title: "Xero settings sync failed",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      });
    } finally {
      setXeroSyncBusy(null);
    }
  }

  async function handleVerifyXeroConnection() {
    setXeroSyncBusy("verify");
    setAccountingError(null);
    try {
      const result = await verifyXeroConnection();
      if (result.connected) {
        toast({
          title: "Connection verified",
          description: result.organisation_name || "Xero organisation verified",
        });
      } else if (result.needs_reauth) {
        toast({
          title: "Reconnect required",
          description: result.message || "Xero session expired",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Verification failed",
          description: result.message || "Could not verify Xero connection",
          variant: "destructive",
        });
      }
    } catch (err) {
      toast({
        title: "Verification failed",
        description: err instanceof Error ? err.message : "Could not verify Xero connection",
        variant: "destructive",
      });
    } finally {
      setXeroSyncBusy(null);
    }
  }

  async function handleSyncXeroContacts() {
    setXeroSyncBusy("contacts");
    setAccountingError(null);
    try {
      const result = await syncXeroContacts();
      toast({
        title: "Xero contacts synced",
        description: `${result.contact} contacts updated`,
      });
    } catch (err) {
      setAccountingError(err instanceof Error ? err.message : "Contacts sync failed");
      toast({
        title: "Xero contacts sync failed",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      });
    } finally {
      setXeroSyncBusy(null);
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
    const gpStatus = globalPayoutsAccessLabel(s?.stripe_global_payouts_access_status);
    return `${mode} · ${masked} · Global Payouts: ${gpStatus}`;
  }, [
    s?.stripe_mode,
    s?.stripe_global_payouts_access_status,
    stripeAccount,
    stripeAccountLoading,
    stripePaymentsConnected,
    stripeReadiness,
    stripeReadinessLoading,
  ]);

  const xeroItem = accountingStatus?.xero;
  const qboItem = accountingStatus?.quickbooks_online;
  const xeroOrgPickerVisible =
    showXeroOrgPicker || needsXeroOrgSelection(xeroReadiness) || xeroReadiness?.status === "organisation_selection_required";
  const xeroConnectedForUi = xeroReadiness?.connected === true || accountingConnected(xeroItem);
  const xeroReady = xeroReadiness?.ready === true;

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
      id: "viber",
      name: "Viber",
      tagline: vbConnections[0]?.bot_id || "Team expense capture",
      ok: vbConnections.some((c) => c.connection_status === "connected"),
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
      id: "foundry-vision",
      name: "Azure AI Foundry (GPT-4o Vision)",
      tagline: "Vision LLM document AI provider",
      ok: Boolean(s.azure_foundry_vision_available),
      icon: Sparkles,
    },
    {
      id: "gemini",
      name: "Gemini Vision",
      tagline: "Legacy optional document AI provider",
      ok: Boolean(s.gemini_vision_available),
      icon: Sparkles,
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
      tagline: xeroReadiness ? xeroStateLabel(xeroReadiness) : accountingTagline(xeroItem, "Chart of accounts & journals"),
      ok: xeroReady || accountingConnected(xeroItem),
      icon: ArrowLeftRight,
      badge: xeroReadiness ? xeroReadinessBadge(xeroReadiness) : accountingStatusBadge(xeroItem),
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
        <div className="space-y-1">
          <Link
            to="/payments"
            className="text-[11px] text-primary hover:underline"
          >
            Manage on Payments
          </Link>
          <p className="text-[11px] text-muted-foreground">
            Global Payouts: {globalPayoutsAccessLabel(s.stripe_global_payouts_access_status)}
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          <Link
            to="/payments"
            className="text-[11px] text-primary hover:underline"
          >
            Connect on Payments
          </Link>
          <p className="text-[11px] text-muted-foreground">
            Global Payouts: {globalPayoutsAccessLabel(s.stripe_global_payouts_access_status)}
          </p>
        </div>
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
      vbConnections,
      xeroItem,
      qboItem,
      xeroReadiness,
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
  const isProductionEnv = (s.app_env || "").toLowerCase() === "production";
  const livePayoutsDisabled =
    isProductionEnv &&
    !(s.stripe_live_payments_enabled && s.stripe_payments_execution_enabled);

  return (
    <div>
      <PageHeader
        title="Integrations"
        subtitle={`${connected} of ${items.length} services connected`}
      />

      <div
        className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground mb-4"
        data-testid="banner-integrations-environment"
      >
        {isProductionEnv
          ? livePayoutsDisabled
            ? "Production environment — live payout execution disabled until Stripe Global Payouts approval is complete."
            : `${s.payment_environment_label} environment`
          : `${s.payment_environment_label} environment — no real money movement`}
      </div>

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
          <p className="text-sm text-muted-foreground">
            {user?.role === "admin"
              ? "No connection requests yet."
              : "No connection requests yet. Only admins can send mailbox invitations."}
          </p>
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
        {visibleMailboxes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {user?.role === "admin" ? (
              <>
                No mailboxes connected yet. Send an invitation above, or set GRAPH_MAILBOX in
                backend .env for legacy application-permission polling.
              </>
            ) : (
              <>No mailboxes connected yet. Ask an admin to send a connection invitation.</>
            )}
          </p>
        ) : (
          <ul className="space-y-2">
            {visibleMailboxes.map((mb) => (
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

      <Card className="p-5 mb-6" id="viber-integration">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Viber</h2>
            <p className="text-xs text-muted-foreground">
              Connect your Viber Public Account bot so employees can submit expense receipts via
              Viber. Identity is matched by Viber user ID or phone in Rule Book → Employees.
            </p>
          </div>
          <MessageCircle className="h-5 w-5 text-muted-foreground" />
        </div>

        {vbError && <p className="text-sm text-destructive mb-2">{vbError}</p>}

        {vbWebhookUrl && (
          <div className="mb-4 rounded-md border border-border bg-muted/40 p-3 space-y-2 max-w-2xl">
            <p className="text-xs text-muted-foreground">
              Webhook URL (registered automatically on connect; must be HTTPS and reachable by
              Viber):
            </p>
            <div className="flex gap-2">
              <Input readOnly value={vbWebhookUrl} className="text-xs font-mono" />
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => void copyInviteLink(vbWebhookUrl)}
              >
                <Copy className="h-4 w-4 mr-1" />
                Copy
              </Button>
            </div>
            {vbWebhookReachable === false && (
              <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive space-y-1">
                <p className="font-medium">Webhook not reachable from the internet</p>
                <p>{vbWebhookHint ?? "Start ngrok and update PUBLIC_TUNNEL_URL in backend .env"}</p>
                <ol className="list-decimal list-inside text-muted-foreground mt-1 space-y-0.5">
                  <li>In a new terminal: <code className="text-[10px]">ngrok http 8001</code></li>
                  <li>
                    Copy the <code className="text-[10px]">https://….ngrok-free.dev</code> URL into{" "}
                    <code className="text-[10px]">PUBLIC_TUNNEL_URL</code> in{" "}
                    <code className="text-[10px]">backend/.env</code>
                  </li>
                  <li>Restart uvicorn, refresh this page, then Connect or Test Viber again</li>
                </ol>
              </div>
            )}
            {vbWebhookReachable === true && (
              <p className="text-xs text-[hsl(var(--chart-1))]">Webhook is reachable (tunnel OK).</p>
            )}
          </div>
        )}

        {user?.role === "admin" && (
          <div className="mb-4 space-y-2 max-w-md">
            <label className="text-xs text-muted-foreground" htmlFor="viber-auth-token">
              Viber auth token (from partners.viber.com → your Public Account)
            </label>
            <div className="flex gap-2">
              <Input
                id="viber-auth-token"
                type="password"
                autoComplete="off"
                placeholder="Paste auth token"
                value={vbAuthToken}
                onChange={(e) => setVbAuthToken(e.target.value)}
                className="text-xs font-mono"
              />
              <Button
                size="sm"
                disabled={vbBusy || vbAuthToken.trim().length < 8}
                onClick={async () => {
                  setVbBusy(true);
                  setVbError(null);
                  try {
                    const result = await api.connectViber(vbAuthToken.trim());
                    setVbAuthToken("");
                    loadViber(true);
                    toast({
                      title: "Viber connected",
                      description: result.bot_name
                        ? `${result.bot_name} is ready for expense capture.`
                        : `Bot ${result.connection.bot_id} connected.`,
                    });
                  } catch (e) {
                    setVbError(e instanceof Error ? e.message : "Could not connect Viber bot");
                  } finally {
                    setVbBusy(false);
                  }
                }}
              >
                {vbBusy ? "Connecting…" : "Connect Viber"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Use the same ngrok URL as <code className="text-[10px]">PUBLIC_TUNNEL_URL</code> in{" "}
              <code className="text-[10px]">backend/.env</code>. Free ngrok URLs change every time
              you restart ngrok — update .env and reconnect Viber after each restart.
            </p>
          </div>
        )}

        {vbConnections.length === 0 ? (
          <p className="text-sm text-muted-foreground">No Viber bots connected yet.</p>
        ) : (
          <ul className="space-y-2">
            {vbConnections.map((conn) => (
              <li
                key={conn.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm gap-3"
              >
                <div className="min-w-0">
                  <span className="font-medium font-mono text-xs">{conn.bot_id}</span>
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    {conn.integration_health}
                  </Badge>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Status: {conn.connection_status}
                  </p>
                </div>
                {user?.role === "admin" && (
                  <div className="flex gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={async () => {
                        try {
                          const result = await api.testViberConnection(conn.id);
                          if (result.ok) {
                            toast({ title: "Viber test passed", description: "Webhook resubscribed." });
                          } else {
                            toast({
                              title: "Viber needs attention",
                              description: result.warnings.join(" · ") || result.integration_health,
                              variant: "destructive",
                            });
                          }
                          loadViber(true);
                        } catch (e) {
                          setVbError(e instanceof Error ? e.message : "Test failed");
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
                          await api.disconnectViber(conn.id);
                          loadViber(true);
                          toast({ title: "Viber disconnected" });
                        } catch (e) {
                          setVbError(e instanceof Error ? e.message : "Disconnect failed");
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

      <Card className="p-5 mb-6" data-testid="panel-xero-integration">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold">Xero accounting</h2>
            <p className="text-xs text-muted-foreground">
              Production OAuth, organisation selection, settings sync, and invoice push to Xero.
            </p>
          </div>
          <ArrowLeftRight className="h-5 w-5 text-muted-foreground" />
        </div>

        {(accountingError || xeroError) && (
          <p className="text-sm text-destructive mb-3">{accountingError ?? xeroError}</p>
        )}

        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs mb-4 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">Readiness</span>
            {xeroReadinessBadge(xeroReadiness)}
            {(accountingLoading || xeroLoading) && (
              <span className="text-muted-foreground">Loading…</span>
            )}
          </div>
          <p className="text-muted-foreground">{xeroStateLabel(xeroReadiness)}</p>
          {xeroReadiness?.display_name && (
            <p className="text-muted-foreground">
              Connected organisation: <span className="text-foreground">{xeroReadiness.display_name}</span>
            </p>
          )}
          {(xeroVerify?.connected || xeroReadiness?.connection_verified) && (
            <p className="text-[hsl(var(--chart-1))]">✓ Connection verified</p>
          )}
          {xeroReadiness?.needs_reauth || xeroVerify?.needs_reauth ? (
            <p className="text-amber-700 dark:text-amber-400">Reconnect required</p>
          ) : null}
          {xeroReadiness?.last_successful_sync_at && (
            <p className="text-muted-foreground">
              Last sync: {new Date(xeroReadiness.last_successful_sync_at).toLocaleString()}
            </p>
          )}
          {(xeroReadiness?.last_error_message || xeroReadiness?.last_error) && (
            <p className="text-destructive">
              Last error: {xeroReadiness.last_error_message || xeroReadiness.last_error}
            </p>
          )}
          {xeroReadiness?.connection_count != null && xeroReadiness.connection_count > 0 && (
            <p className="text-muted-foreground">
              {xeroReadiness.connection_count} organisation
              {xeroReadiness.connection_count === 1 ? "" : "s"} available
            </p>
          )}
        </div>

        {!s.xero_configured && (
          <p className="text-sm text-muted-foreground mb-4">
            Set XERO_CLIENT_ID and XERO_CLIENT_SECRET in backend environment to enable OAuth.
          </p>
        )}

        {user?.role === "admin" && s.xero_configured && !xeroConnectedForUi && (
          <div className="mb-4">
            <Button
              size="sm"
              disabled={accountingBusy === "xero" || accountingLoading}
              onClick={() => void startAccountingConnect("xero")}
            >
              {accountingBusy === "xero" ? "Redirecting…" : "Connect Xero"}
            </Button>
          </div>
        )}

        {xeroOrgPickerVisible && xeroConnections.length > 0 && (
          <div className="mb-4 space-y-2" data-testid="xero-org-picker">
            <p className="text-xs font-medium">Select Xero organisation</p>
            <ul className="space-y-2">
              {xeroConnections.map((conn) => (
                <li
                  key={conn.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm gap-3"
                >
                  <div className="min-w-0">
                    <span className="font-medium">
                      {conn.xero_tenant_name || conn.xero_tenant_id}
                    </span>
                    {conn.selected && (
                      <Badge variant="outline" className="ml-2 text-[10px]">
                        Selected
                      </Badge>
                    )}
                  </div>
                  {user?.role === "admin" && !conn.selected && (
                    <Button
                      size="sm"
                      className="h-7 text-xs shrink-0"
                      disabled={xeroSyncBusy === "select"}
                      onClick={() => void handleSelectXeroOrg(conn.xero_connection_id)}
                    >
                      {xeroSyncBusy === "select" ? "Selecting…" : "Use this org"}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {user?.role === "admin" && xeroReady && (
          <div className="flex flex-wrap gap-2 mb-4">
            <Button
              size="sm"
              variant="outline"
              disabled={xeroSyncBusy != null}
              onClick={() => void handleVerifyXeroConnection()}
            >
              {xeroSyncBusy === "verify" ? "Verifying…" : "Verify connection"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={xeroSyncBusy != null}
              onClick={() => void handleSyncXeroSettings()}
            >
              {xeroSyncBusy === "settings" ? "Syncing settings…" : "Sync settings"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={xeroSyncBusy != null}
              onClick={() => void handleSyncXeroContacts()}
            >
              {xeroSyncBusy === "contacts" ? "Syncing contacts…" : "Sync contacts"}
            </Button>
          </div>
        )}

        {user?.role === "admin" && xeroConnectedForUi && (
          <div className="flex flex-wrap gap-2">
            {(xeroReadiness?.needs_reauth || xeroVerify?.needs_reauth) && (
              <Button
                size="sm"
                disabled={accountingBusy === "xero"}
                onClick={() => void startAccountingConnect("xero")}
              >
                {accountingBusy === "xero" ? "Redirecting…" : "Reconnect Xero"}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={accountingBusy === "xero" || accountingLoading}
              onClick={() => void disconnectAccounting("xero")}
            >
              {accountingBusy === "xero" ? "Disconnecting…" : "Disconnect Xero"}
            </Button>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="text-sm font-semibold mb-1">Planned QuickBooks sync</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Xero settings, contacts, and invoice push are live. QuickBooks bill and journal sync is
          not enabled yet. Planned features:
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
