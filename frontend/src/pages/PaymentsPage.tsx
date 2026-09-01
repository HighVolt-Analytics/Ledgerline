import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link2, Settings2, Shield } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { BankFileSettingsDialog } from "@/components/payments/BankFileSettingsDialog";
import { PaymentReceiptSheet } from "@/components/payments/PaymentReceiptSheet";
import { PaymentRow } from "@/components/payments/PaymentRow";
import { PayPalProviderCard } from "@/components/payments/PayPalProviderCard";
import { WalletCard } from "@/components/payments/WalletCard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import {
  PAYMENTS_PAGE_SIZE,
  useDownloadBatchPaymentBankFile,
  usePaymentMutations,
  usePaymentWorkspaceKpis,
  usePayments,
  useAppSettings,
} from "@/hooks/usePayments";
import { useToast } from "@/context/ToastContext";
import {
  useConnectStripe,
  useDisconnectStripe,
  useRefreshStripeAccount,
  useStripeAccount,
  useStripeBalance,
  useStripeGlobalPayoutsReadiness,
  useStripeOnboardingLink,
  useStripeOAuthUrl,
  useStripeReadiness,
  useStripeTransactions,
} from "@/hooks/useStripe";
import { useRefreshPayPalReadiness } from "@/hooks/usePayPal";
import type { StripeAccount, StripeBalanceAmount, StripeReadinessResponse } from "@/api/types";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { apiPaymentToRecord } from "@/lib/routePageAdapters";
import { paymentTierLabel, type PaymentRecord, type PaymentTab } from "@/lib/v4MockData";

const TABS: { value: PaymentTab; label: string; testid: string }[] = [
  { value: "queue", label: "Queue", testid: "tab-pay-queue" },
  { value: "awaiting", label: "Awaiting approval", testid: "tab-pay-awaiting" },
  { value: "scheduled", label: "Scheduled", testid: "tab-pay-scheduled" },
  { value: "paid", label: "Paid", testid: "tab-pay-paid" },
  { value: "failed", label: "Failed", testid: "tab-pay-failed" },
];

function stripeNeedsOnboarding(account: StripeAccount): boolean {
  if (account.onboarding_status === "disconnected") return false;
  if (account.account_type === "standard") return false;
  if (account.onboarding_status === "complete") return false;
  if (!account.details_submitted) return true;
  if (!account.charges_enabled || !account.payouts_enabled) return true;
  return (
    account.onboarding_status == null ||
    account.onboarding_status === "pending" ||
    account.onboarding_status === "action_required"
  );
}

function maskStripeAccountId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 8)}…${id.slice(-4)}`;
}

function formatBalanceLine(
  label: string,
  items: StripeBalanceAmount[],
): string {
  if (!items.length) return `${label}: —`;
  const parts = items
    .filter((item) => item.amount != null)
    .map((item) => money(item.amount, item.currency));
  return `${label}: ${parts.length ? parts.join(" · ") : "—"}`;
}

function sumStripeBalanceAmounts(
  items: StripeBalanceAmount[],
): { total: number; currency: string } {
  const withAmount = items.filter((item) => item.amount != null);
  if (!withAmount.length) {
    return { total: 0, currency: "" };
  }
  const currency = withAmount[0]?.currency || "";
  const total = withAmount.reduce((sum, item) => sum + (item.amount ?? 0), 0);
  return { total, currency };
}

function stripeModeLabel(livemode: boolean | undefined): string {
  if (livemode === true) return "Live mode";
  if (livemode === false) return "Test mode";
  return "Sandbox";
}

function globalPayoutsAccessLabel(status: string | undefined): string {
  const normalized = (status || "not_requested").toLowerCase();
  if (normalized === "pending_approval") return "Pending approval";
  if (normalized === "enabled") return "Enabled";
  if (normalized === "rejected") return "Rejected";
  return "Not requested";
}

function paymentEnvironmentBanner(
  appSettings: {
    app_env?: string;
    payment_environment_label?: string;
    stripe_global_payouts_access_status?: string;
    stripe_live_payments_enabled?: boolean;
    stripe_payments_execution_enabled?: boolean;
  } | null | undefined,
  globalPayoutsLiveExecution: boolean | undefined
): { message: string; tone: "info" | "warning" } | null {
  if (!appSettings) return null;
  const env = (appSettings.app_env || "preview").toLowerCase();
  const label = appSettings.payment_environment_label || "Preview";
  if (env !== "production") {
    return {
      tone: "info",
      message: `${label} environment — no real money movement`,
    };
  }
  if (!globalPayoutsLiveExecution) {
    return {
      tone: "warning",
      message:
        "Production environment — live payout execution disabled until Stripe Global Payouts approval is complete.",
    };
  }
  return null;
}

function stripeReadinessBanner(
  readiness: StripeReadinessResponse | undefined
): { message: string; tone: "success" | "warning" | "neutral" } | null {
  if (!readiness) return null;
  if (!readiness.connected) {
    return {
      tone: "neutral",
      message: "Connect Stripe below to view balance and readiness for charges and payouts.",
    };
  }
  if (readiness.ready_for_charges && readiness.ready_for_payouts) {
    return { tone: "success", message: "Stripe ready for charges and payouts." };
  }
  if (readiness.ready_for_charges && !readiness.ready_for_payouts) {
    return {
      tone: "warning",
      message: "Stripe ready for charges. Payouts are still disabled.",
    };
  }
  if (readiness.blocking_reason === "Stripe onboarding is incomplete") {
    return {
      tone: "warning",
      message: "Stripe setup incomplete. Complete onboarding before enabling payouts.",
    };
  }
  return {
    tone: "warning",
    message: readiness.blocking_reason ?? "Stripe setup is incomplete.",
  };
}

export function PaymentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const stripeReturnHandled = useRef(false);
  const paypalReturnHandled = useRef(false);
  const [tab, setTab] = useState<PaymentTab>("queue");
  const { data: paymentRows = [], isLoading: paymentsLoading, isError, blocked: paymentsBlocked } =
    usePayments(tab);
  const { toast } = useToast();
  const [selectedPaymentIds, setSelectedPaymentIds] = useState<Set<number>>(new Set());
  const downloadBankFile = useDownloadBatchPaymentBankFile();
  const handleTabChange = (nextTab: PaymentTab) => {
    setTab(nextTab);
    setSelectedPaymentIds(new Set());
  };
  const toggleSelectPayment = (paymentId: number) => {
    setSelectedPaymentIds((prev) => {
      const next = new Set(prev);
      if (next.has(paymentId)) next.delete(paymentId);
      else next.add(paymentId);
      return next;
    });
  };
  const handleDownloadBankFile = async () => {
    try {
      await downloadBankFile.mutateAsync(Array.from(selectedPaymentIds));
      setSelectedPaymentIds(new Set());
      toast({ title: "Bank payment file downloaded" });
    } catch (err) {
      toast({
        title: "Could not export bank payment file",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    }
  };
  const {
    data: kpis,
    isLoading: kpisLoading,
  } = usePaymentWorkspaceKpis();
  const { data: appSettings } = useAppSettings();
  const isLoading = paymentsLoading || paymentsBlocked;
  const showKpiPlaceholder = kpisLoading || paymentsBlocked;
  const paymentsExecutionEnabled = appSettings?.stripe_payments_execution_enabled ?? false;
  const manualExecutionEnabled =
    (appSettings?.payment_manual_execution_enabled ?? false) &&
    !(appSettings?.payment_execution_disabled ?? false);
  const { updateStatus, approvePayment } = usePaymentMutations();
  const { data: stripeAccount, isLoading: stripeAccountLoading } = useStripeAccount();
  const { data: stripeReadiness } = useStripeReadiness();
  const { data: globalPayoutsReadiness, isLoading: globalPayoutsLoading } =
    useStripeGlobalPayoutsReadiness();
  const stripeConnected = stripeAccount != null;
  const { data: stripeBalance, isLoading: stripeBalanceLoading } = useStripeBalance(
    stripeConnected
  );
  const { data: stripeTransactions = [], isLoading: stripeTransactionsLoading } =
    useStripeTransactions(10, stripeConnected);
  const connectStripe = useConnectStripe();
  const disconnectStripe = useDisconnectStripe();
  const refreshStripeAccount = useRefreshStripeAccount();
  const refreshPayPalReadiness = useRefreshPayPalReadiness();
  const onboardingLink = useStripeOnboardingLink();
  const stripeOAuthUrl = useStripeOAuthUrl();
  const [justPaidId, setJustPaidId] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PaymentRecord | null>(null);
  const [bankFileSettingsOpen, setBankFileSettingsOpen] = useState(false);
  const [stripeActionError, setStripeActionError] = useState<string | null>(null);
  const [paypalActionError, setPaypalActionError] = useState<string | null>(null);

  const payments = useMemo(() => paymentRows.map(apiPaymentToRecord), [paymentRows]);
  const tabCount =
    tab === "queue"
      ? kpis?.queue_count
      : tab === "awaiting"
        ? kpis?.awaiting_count
        : tab === "scheduled"
          ? kpis?.scheduled_count
          : tab === "paid"
            ? kpis?.paid_count
            : kpis?.failed_count;
  const needsOnboarding = stripeAccount ? stripeNeedsOnboarding(stripeAccount) : false;
  const stripeWalletAvailable = sumStripeBalanceAmounts(
    stripeBalance?.available ?? []
  );
  const stripeWalletPending = sumStripeBalanceAmounts(
    stripeBalance?.pending ?? []
  );
  const readinessBanner = stripeReadinessBanner(stripeReadiness);
  const environmentBanner = paymentEnvironmentBanner(
    appSettings,
    globalPayoutsReadiness?.live_execution_enabled
  );

  useEffect(() => {
    const stripeReturn = searchParams.get("stripe");
    if (!stripeReturn) return;
    if (stripeReturnHandled.current) return;
    stripeReturnHandled.current = true;

    const message = searchParams.get("message");
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("stripe");
    nextParams.delete("message");
    setSearchParams(nextParams, { replace: true });

    if (stripeReturn === "oauth_error") {
      setStripeActionError(message || "Stripe connection failed");
      return;
    }

    if (stripeReturn === "connected" || stripeReturn === "return") {
      void refreshStripeAccount.mutateAsync().catch((err: unknown) => {
        setStripeActionError(
          err instanceof Error ? err.message : "Unable to refresh Stripe account status"
        );
      });
    }
  }, [refreshStripeAccount, searchParams, setSearchParams]);

  useEffect(() => {
    const paypalReturn = searchParams.get("paypal");
    if (!paypalReturn) return;
    if (paypalReturnHandled.current) return;
    paypalReturnHandled.current = true;

    const message = searchParams.get("message");
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("paypal");
    nextParams.delete("message");
    setSearchParams(nextParams, { replace: true });

    if (paypalReturn === "error") {
      setPaypalActionError(message || "PayPal connection failed");
      return;
    }

    if (paypalReturn === "connected" || paypalReturn === "pending") {
      void refreshPayPalReadiness.mutateAsync().catch((err: unknown) => {
        setPaypalActionError(
          err instanceof Error ? err.message : "Unable to refresh PayPal account status"
        );
      });
    }
  }, [refreshPayPalReadiness, searchParams, setSearchParams]);

  const advance = async (payment: PaymentRecord, status: string) => {
    await updateStatus(Number(payment.id), { status });
    if (status === "paid") {
      setJustPaidId(payment.id);
      setTimeout(() => setJustPaidId(null), 2000);
    }
  };

  const handleApprovePayment = async (payment: PaymentRecord) => {
    setApprovingId(payment.id);
    try {
      await approvePayment(Number(payment.id));
    } finally {
      setApprovingId(null);
    }
  };

  const handleConnectStripe = async () => {
    setStripeActionError(null);
    try {
      const result = await connectStripe.mutateAsync();
      if (result.onboarding_url) {
        window.location.href = result.onboarding_url;
      }
    } catch (err) {
      setStripeActionError(err instanceof Error ? err.message : "Unable to connect Stripe");
    }
  };

  const handleConnectExistingStripe = async () => {
    setStripeActionError(null);
    try {
      const result = await stripeOAuthUrl.mutateAsync();
      window.location.href = result.url;
    } catch (err) {
      setStripeActionError(
        err instanceof Error ? err.message : "Unable to start Stripe sign-in"
      );
    }
  };

  const handleContinueOnboarding = async () => {
    setStripeActionError(null);
    try {
      const result = await onboardingLink.mutateAsync();
      window.location.href = result.url;
    } catch (err) {
      setStripeActionError(err instanceof Error ? err.message : "Unable to open onboarding");
    }
  };

  const handleRefreshStripeStatus = async () => {
    setStripeActionError(null);
    try {
      await refreshStripeAccount.mutateAsync();
    } catch (err) {
      setStripeActionError(
        err instanceof Error ? err.message : "Unable to refresh Stripe account status"
      );
    }
  };

  const handleDisconnectStripe = async () => {
    const confirmed = window.confirm(
      "Disconnect this Stripe account from LedgerLink? You can reconnect another Stripe account after this."
    );
    if (!confirmed) return;

    setStripeActionError(null);
    try {
      await disconnectStripe.mutateAsync();
    } catch (err) {
      setStripeActionError(
        err instanceof Error ? err.message : "Unable to disconnect Stripe account"
      );
    }
  };

  const stripeConnectBusy =
    connectStripe.isPending ||
    stripeOAuthUrl.isPending ||
    disconnectStripe.isPending ||
    refreshStripeAccount.isPending;

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Disbursement workflow for processed payables — tiered approval by amount with Stripe-ready scheduling."
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => setBankFileSettingsOpen(true)}
            data-testid="open-bank-file-settings"
          >
            <Settings2 className="h-3.5 w-3.5 mr-1.5" />
            Bank file settings
          </Button>
        }
      />

      {environmentBanner ? (
        <div
          className={cn(
            "rounded-md border px-3 py-2 text-xs mb-4",
            environmentBanner.tone === "info" &&
              "border-border bg-muted/40 text-muted-foreground",
            environmentBanner.tone === "warning" &&
              "ds-warning-panel border ds-warning-text"
          )}
          data-testid="banner-payment-environment"
        >
          {environmentBanner.message}
        </div>
      ) : null}

      <div className="grid gap-3 grid-cols-1 lg:grid-cols-[1fr_1fr_1fr_1.4fr] mb-5">
        <KpiCard
          label="Open payables"
          value={showKpiPlaceholder ? "…" : (kpis?.open_count ?? 0)}
          testid="kpi-pay-ready"
          delta={{ dir: "up", text: "workflow queue", good: true }}
        />
        <KpiCard
          label="Due within 7 days"
          value={showKpiPlaceholder ? "…" : (kpis?.due_soon_count ?? 0)}
          testid="kpi-pay-awaiting"
          delta={
            !showKpiPlaceholder && (kpis?.due_soon_count ?? 0) > 0
              ? { dir: "flat", text: "coming due" }
              : undefined
          }
        />
        <KpiCard
          label="Queue total"
          value={showKpiPlaceholder ? "…" : formatMoneyByCurrencyMap(kpis?.outstanding_by_currency ?? {})}
          testid="kpi-pay-paid"
        />
        <WalletCard
          stripeConnected={stripeConnected}
          stripeLoading={stripeAccountLoading || stripeBalanceLoading}
          stripeAvailableTotal={stripeWalletAvailable.total}
          stripePendingTotal={stripeWalletPending.total}
          stripeCurrency={stripeWalletAvailable.currency || stripeWalletPending.currency}
          stripeLivemode={stripeBalance?.livemode}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2 mb-5 items-start">
        <Card className="p-4 mb-0" data-testid="card-stripe-connect">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div className="flex items-start gap-2.5">
            <Link2 className="h-4 w-4 text-primary mt-0.5 shrink-0" />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-medium">Stripe Connect</h2>
                <span
                  className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                  data-testid="badge-stripe-mode"
                >
                  {stripeModeLabel(stripeBalance?.livemode)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Connect a Stripe account to view balance and ledger activity. Payables workflow
                below is unchanged.
              </p>
            </div>
          </div>
          {stripeConnected ? (
            <div className="flex flex-wrap gap-2">
              {needsOnboarding ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void handleContinueOnboarding()}
                  disabled={onboardingLink.isPending || stripeConnectBusy}
                  data-testid="button-continue-onboarding"
                >
                  {onboardingLink.isPending ? "Opening…" : "Continue onboarding"}
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleDisconnectStripe()}
                disabled={stripeConnectBusy}
                data-testid="button-disconnect-stripe"
              >
                {disconnectStripe.isPending ? "Disconnecting…" : "Disconnect Stripe"}
              </Button>
            </div>
          ) : null}
        </div>

        {stripeActionError ? (
          <p className="text-xs text-destructive mb-3">{stripeActionError}</p>
        ) : null}

        {readinessBanner ? (
          <div
            className={cn(
              "rounded-md border px-3 py-2 text-xs mb-3",
              readinessBanner.tone === "success" &&
                "border-primary/30 bg-primary/10 text-primary",
              readinessBanner.tone === "warning" &&
                "ds-warning-panel border ds-warning-text",
              readinessBanner.tone === "neutral" &&
                "border-border bg-muted/40 text-muted-foreground"
            )}
            data-testid="stripe-readiness-banner"
          >
            <p>{readinessBanner.message}</p>
            {readinessBanner.tone === "warning" && stripeReadiness?.recommended_action ? (
              <p className="mt-1 opacity-90">{stripeReadiness.recommended_action}</p>
            ) : null}
          </div>
        ) : null}

        {stripeAccountLoading ? (
          <p className="text-xs text-muted-foreground">Loading Stripe connection…</p>
        ) : !stripeConnected ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              className="text-left rounded-md border border-border bg-card p-4 transition-colors hover:bg-muted/40 disabled:opacity-50 disabled:pointer-events-none"
              onClick={() => void handleConnectExistingStripe()}
              disabled={stripeConnectBusy}
              data-testid="card-stripe-oauth-choice"
            >
              <h3 className="text-sm font-medium text-foreground">I already use Stripe</h3>
              <p className="text-xs text-muted-foreground mt-1.5">
                Sign in to Stripe and authorize LedgerLink.
              </p>
              <p className="text-xs text-primary mt-3">
                {stripeOAuthUrl.isPending ? "Redirecting…" : "Connect existing account"}
              </p>
            </button>
            <button
              type="button"
              className="text-left rounded-md border border-border bg-card p-4 transition-colors hover:bg-muted/40 disabled:opacity-50 disabled:pointer-events-none"
              onClick={() => void handleConnectStripe()}
              disabled={stripeConnectBusy}
              data-testid="card-stripe-express-choice"
            >
              <h3 className="text-sm font-medium text-foreground">I don&apos;t have Stripe yet</h3>
              <p className="text-xs text-muted-foreground mt-1.5">
                Create a new connected Stripe account with hosted onboarding.
              </p>
              <p className="text-xs text-primary mt-3">
                {connectStripe.isPending ? "Connecting…" : "Create new account"}
              </p>
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Account status
              </span>
              <Button
                type="button"
                size="sm"
                variant="surface"
                onClick={() => void handleRefreshStripeStatus()}
                disabled={stripeConnectBusy}
                data-testid="button-refresh-stripe-status"
              >
                {refreshStripeAccount.isPending ? "Refreshing…" : "Refresh status"}
              </Button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs">
              <div>
                <span className="text-muted-foreground">Account</span>
                <div className="font-mono text-foreground">
                  {maskStripeAccountId(stripeAccount.stripe_account_id)}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Onboarding</span>
                <div className="text-foreground capitalize">
                  {stripeAccount.onboarding_status?.replace(/_/g, " ") ?? "—"}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Charges</span>
                <div className="text-foreground">
                  {stripeAccount.charges_enabled ? "Enabled" : "Disabled"}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Payouts</span>
                <div className="text-foreground">
                  {stripeAccount.payouts_enabled ? "Enabled" : "Disabled"}
                </div>
              </div>
            </div>

            <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs">
              {stripeBalanceLoading ? (
                <span className="text-muted-foreground">Loading balance…</span>
              ) : stripeBalance ? (
                <div className="space-y-1 tnum">
                  <div>{formatBalanceLine("Available", stripeBalance.available)}</div>
                  <div>{formatBalanceLine("Pending", stripeBalance.pending)}</div>
                </div>
              ) : (
                <span className="text-muted-foreground">Balance unavailable</span>
              )}
            </div>

            <div>
              <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Recent Stripe transactions
              </h3>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm" data-testid="table-stripe-transactions">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground border-b border-border">
                      <th className="px-3 py-2 font-medium">Available</th>
                      <th className="px-3 py-2 font-medium">Description</th>
                      <th className="px-3 py-2 font-medium">Type</th>
                      <th className="px-3 py-2 font-medium text-right">Amount</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stripeTransactionsLoading ? (
                      <tr>
                        <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                          Loading transactions…
                        </td>
                      </tr>
                    ) : stripeTransactions.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                          No Stripe transactions yet.
                        </td>
                      </tr>
                    ) : (
                      stripeTransactions.map((txn) => (
                        <tr
                          key={txn.id}
                          className="border-b border-border/60 last:border-0 hover-elevate"
                        >
                          <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                            {txn.available_on ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs">
                            {txn.description ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">
                            {txn.type ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-right tnum whitespace-nowrap">
                            {txn.amount != null
                              ? money(txn.amount, txn.currency)
                              : "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">
                            {txn.status ?? "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        <p className="text-[11px] text-muted-foreground mt-3 border-t border-border/60 pt-3">
          Stripe Connect is used for account connection and visibility. Australia/AUD supplier AP
          payments require Stripe Global Payouts approval.
        </p>
      </Card>

      <div>
        {paypalActionError ? (
          <p className="text-xs text-destructive mb-2" data-testid="paypal-page-error">
            {paypalActionError}
          </p>
        ) : null}
        <PayPalProviderCard />
      </div>
      </div>

      <Card className="p-4 mb-5" data-testid="card-stripe-global-payouts">
        <div className="flex items-start gap-2.5 mb-3">
          <Shield className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <div>
            <h2 className="text-sm font-medium">Stripe Global Payouts</h2>
            <p className="text-xs text-muted-foreground mt-1">
              Configuration readiness for Australia/AUD supplier AP payments. No outbound payment
              APIs are called until Stripe approval and explicit live execution flags are enabled.
            </p>
          </div>
        </div>
        {globalPayoutsLoading || !globalPayoutsReadiness ? (
          <p className="text-xs text-muted-foreground">Loading Global Payouts readiness…</p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 text-xs">
            <div>
              <span className="text-muted-foreground">Environment</span>
              <div className="text-foreground capitalize">{globalPayoutsReadiness.environment}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Stripe mode</span>
              <div className="text-foreground uppercase">{globalPayoutsReadiness.stripe_mode}</div>
            </div>
            <div>
              <span className="text-muted-foreground">Access status</span>
              <div className="text-foreground">
                {globalPayoutsAccessLabel(globalPayoutsReadiness.access_status)}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Financial account</span>
              <div className="text-foreground">
                {globalPayoutsReadiness.financial_account_configured
                  ? "Configured"
                  : "Not configured"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Supported</span>
              <div className="text-foreground">
                {globalPayoutsReadiness.supported_countries.join(", ") || "—"} ·{" "}
                {globalPayoutsReadiness.supported_currencies.join(", ") || "—"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Launch limit</span>
              <div className="text-foreground tnum">
                USD {globalPayoutsReadiness.max_amount_usd.toLocaleString()}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Ready</span>
              <div className={globalPayoutsReadiness.ready ? "text-primary" : "text-foreground"}>
                {globalPayoutsReadiness.ready ? "Yes" : "No"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Live execution</span>
              <div className="text-foreground">
                {globalPayoutsReadiness.live_execution_enabled ? "Enabled" : "Disabled"}
              </div>
            </div>
          </div>
        )}
        {globalPayoutsReadiness?.blocking_reason ? (
          <p className="text-xs text-muted-foreground mt-3">{globalPayoutsReadiness.blocking_reason}</p>
        ) : null}
        {globalPayoutsReadiness?.recommended_action ? (
          <p className="text-xs text-muted-foreground mt-1">
            {globalPayoutsReadiness.recommended_action}
          </p>
        ) : null}
      </Card>

      <Card className="p-3 mb-5 ds-warning-panel border">
        <div className="flex items-start gap-2.5">
          <Shield className="h-4 w-4 ds-warning-text mt-0.5 shrink-0" />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">
              Real Stripe payouts are disabled.
            </span>{" "}
            LedgerLink is currently in client-controlled manual execution mode. It can create
            payment instructions and record manual payment completion, but it does not move funds.
            Launch limit: USD {appSettings?.payment_manual_execution_limit_usd ?? 1000} per payment.
            Use <span className="text-foreground">Validate payment</span> for dry-run readiness
            checks.
            {paymentsExecutionEnabled ? (
              <span className="block mt-1 ds-warning-text">
                STRIPE_PAYMENTS_EXECUTION_ENABLED is true in server config, but real execution
                endpoints are not enabled in this build.
              </span>
            ) : null}
            {!manualExecutionEnabled ? (
              <span className="block mt-1">
                Manual instruction orchestration is disabled (
                <span className="font-mono text-[10px]">PAYMENT_MANUAL_EXECUTION_ENABLED</span>
                ).
              </span>
            ) : null}
          </div>
        </div>
      </Card>

      <Card className="p-3 mb-5 border-primary/30 bg-primary/5">
        <div className="flex items-start gap-2.5">
          <Shield className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Payment controls active.</span> Payments
            are created when invoices reach <span className="text-foreground">processed</span> with
            a due date. Multi-tier approval scales with amount (
            {paymentTierLabel(500)}, {paymentTierLabel(5000)}, {paymentTierLabel(25000)},{" "}
            {paymentTierLabel(60000)}).
          </div>
        </div>
      </Card>

      <PageTabs
        value={tab}
        onChange={(v) => handleTabChange(v as PaymentTab)}
        tabs={TABS.map((t) => ({
          ...t,
          label:
            kpis == null
              ? t.label
              : `${t.label} (${
                  t.value === "queue"
                    ? kpis.queue_count
                    : t.value === "awaiting"
                      ? kpis.awaiting_count
                      : t.value === "scheduled"
                        ? kpis.scheduled_count
                        : t.value === "paid"
                          ? kpis.paid_count
                          : kpis.failed_count
                })`,
        }))}
      />

      {tab === "scheduled" && payments.length > 0 ? (
        <div className="mt-3 flex items-center justify-between gap-3 rounded-md border border-border bg-muted/30 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {selectedPaymentIds.size > 0
              ? `${selectedPaymentIds.size} payment${selectedPaymentIds.size === 1 ? "" : "s"} selected`
              : "Select Scheduled payments to bundle into one batch bank payment file (e.g. an AU ABA export)."}
          </span>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setBankFileSettingsOpen(true)}
              data-testid="open-bank-file-settings-scheduled"
            >
              Bank file settings
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={selectedPaymentIds.size === 0 || downloadBankFile.isPending}
              onClick={() => void handleDownloadBankFile()}
              data-testid="download-batch-bank-file"
            >
              {downloadBankFile.isPending ? "Preparing file…" : "Download bank file"}
            </Button>
          </div>
        </div>
      ) : null}

      <PageTabPanel value={tab} active={tab} className="mt-4">
        {isLoading ? (
          <TableSkeleton rows={7} columns={5} />
        ) : isError && !paymentsBlocked ? (
          <div className="text-sm text-destructive py-8">Could not load payments.</div>
        ) : payments.length === 0 ? (
          <EmptyState
            className="mt-0 w-full max-w-none"
            title={`No ${tab} payments`}
            hint="Processed invoices with due dates create payment rows automatically."
          />
        ) : (
          <div className="space-y-2.5">
            {payments.map((payment) => (
              <PaymentRow
                key={payment.id}
                payment={payment}
                justPaid={justPaidId === payment.id}
                paymentsExecutionEnabled={paymentsExecutionEnabled}
                manualExecutionEnabled={manualExecutionEnabled}
                approveBusy={approvingId === payment.id}
                selectable={tab === "scheduled"}
                selected={selectedPaymentIds.has(Number(payment.id))}
                onToggleSelect={() => toggleSelectPayment(Number(payment.id))}
                onSubmit={() => void advance(payment, "awaiting")}
                onApprove={() => void handleApprovePayment(payment)}
                onPayNow={() => void advance(payment, "paid")}
                onReceipt={() => setReceipt(payment)}
              />
            ))}
            {tabCount != null && tabCount > payments.length ? (
              <p className="text-xs text-muted-foreground px-1 pt-1">
                Showing {payments.length} of {tabCount}
                {tabCount > PAYMENTS_PAGE_SIZE ? ` (first ${PAYMENTS_PAGE_SIZE})` : ""}.
              </p>
            ) : null}
          </div>
        )}
      </PageTabPanel>

      <PaymentReceiptSheet
        open={!!receipt}
        onClose={() => setReceipt(null)}
        payment={receipt}
      />

      <BankFileSettingsDialog
        open={bankFileSettingsOpen}
        onClose={() => setBankFileSettingsOpen(false)}
      />
    </div>
  );
}
