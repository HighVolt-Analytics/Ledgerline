import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Link2, Shield } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { PaymentReceiptSheet } from "@/components/payments/PaymentReceiptSheet";
import { PaymentRow } from "@/components/payments/PaymentRow";
import { WalletCard } from "@/components/payments/WalletCard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePaymentMutations, usePayments, useAppSettings } from "@/hooks/usePayments";
import {
  useConnectStripe,
  useDisconnectStripe,
  useRefreshStripeAccount,
  useStripeAccount,
  useStripeBalance,
  useStripeOnboardingLink,
  useStripeOAuthUrl,
  useStripeReadiness,
  useStripeTransactions,
} from "@/hooks/useStripe";
import { useTenantTime } from "@/hooks/useTenantTime";
import type { StripeAccount, StripeBalanceAmount, StripeReadinessResponse } from "@/api/types";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { apiPaymentToRecord, paymentsKpis } from "@/lib/routePageAdapters";
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

function formatBalanceLine(label: string, items: StripeBalanceAmount[]): string {
  if (!items.length) return `${label}: —`;
  const parts = items
    .filter((item) => item.amount != null)
    .map((item) => money(item.amount, item.currency ?? "AUD"));
  return `${label}: ${parts.length ? parts.join(" · ") : "—"}`;
}

function stripeModeLabel(livemode: boolean | undefined): string {
  if (livemode === true) return "Live mode";
  if (livemode === false) return "Test mode";
  return "Sandbox";
}

function sumStripeBalanceAmounts(
  items: StripeBalanceAmount[]
): { total: number; currency: string } {
  const withAmount = items.filter((item) => item.amount != null);
  if (!withAmount.length) {
    return { total: 0, currency: "AUD" };
  }
  const currency = withAmount[0]?.currency ?? "AUD";
  const total = withAmount.reduce((sum, item) => sum + (item.amount ?? 0), 0);
  return { total, currency };
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
  const { timeZone } = useTenantTime();
  const { data: paymentRows = [], isLoading, isError } = usePayments();
  const { data: appSettings } = useAppSettings();
  const paymentsExecutionEnabled = appSettings?.stripe_payments_execution_enabled ?? false;
  const manualExecutionEnabled =
    (appSettings?.payment_manual_execution_enabled ?? false) &&
    !(appSettings?.payment_execution_disabled ?? false);
  const { updateStatus, approvePayment } = usePaymentMutations();
  const { data: stripeAccount, isLoading: stripeAccountLoading } = useStripeAccount();
  const { data: stripeReadiness } = useStripeReadiness();
  const stripeConnected = stripeAccount != null;
  const { data: stripeBalance, isLoading: stripeBalanceLoading } = useStripeBalance(
    stripeConnected
  );
  const { data: stripeTransactions = [], isLoading: stripeTransactionsLoading } =
    useStripeTransactions(10, stripeConnected);
  const connectStripe = useConnectStripe();
  const disconnectStripe = useDisconnectStripe();
  const refreshStripeAccount = useRefreshStripeAccount();
  const onboardingLink = useStripeOnboardingLink();
  const stripeOAuthUrl = useStripeOAuthUrl();
  const [tab, setTab] = useState<PaymentTab>("queue");
  const [justPaidId, setJustPaidId] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PaymentRecord | null>(null);
  const [stripeActionError, setStripeActionError] = useState<string | null>(null);

  const payments = useMemo(() => paymentRows.map(apiPaymentToRecord), [paymentRows]);
  const kpis = paymentsKpis(payments, timeZone);
  const tabPayments = useMemo(
    () => payments.filter((p) => p.tab === tab),
    [payments, tab]
  );
  const needsOnboarding = stripeAccount ? stripeNeedsOnboarding(stripeAccount) : false;
  const stripeWalletAvailable = sumStripeBalanceAmounts(stripeBalance?.available ?? []);
  const stripeWalletPending = sumStripeBalanceAmounts(stripeBalance?.pending ?? []);
  const readinessBanner = stripeReadinessBanner(stripeReadiness);

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
      />

      <div className="grid gap-3 grid-cols-1 lg:grid-cols-[1fr_1fr_1fr_1.4fr] mb-5">
        <KpiCard
          label="Open payables"
          value={isLoading ? "…" : kpis.count}
          testid="kpi-pay-ready"
          delta={{ dir: "up", text: "workflow queue", good: true }}
        />
        <KpiCard
          label="Due within 7 days"
          value={isLoading ? "…" : kpis.dueSoon}
          testid="kpi-pay-awaiting"
          delta={
            !isLoading && kpis.dueSoon > 0 ? { dir: "flat", text: "coming due" } : undefined
          }
        />
        <KpiCard
          label="Queue total"
          value={isLoading ? "…" : money(kpis.total)}
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

      <Card className="p-4 mb-5" data-testid="card-stripe-connect">
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
                "border-[hsl(36_80%_70%)] bg-[hsl(36_80%_96%)] text-[hsl(36_80%_28%)] dark:border-[hsl(43_74%_35%)] dark:bg-[hsl(43_74%_12%)] dark:text-[hsl(43_74%_72%)]",
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
                variant="ghost"
                className="h-7 text-xs px-2"
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
                              ? money(txn.amount, txn.currency ?? "AUD")
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
          External supplier bank payouts — Phase 2. Vendor payout rails are not enabled yet; Top Up
          and Withdraw remain unavailable until supported by the backend.
        </p>
      </Card>

      <Card className="p-3 mb-5 border-amber-500/30 bg-amber-500/5">
        <div className="flex items-start gap-2.5">
          <Shield className="h-4 w-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
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
              <span className="block mt-1 text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]">
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

      <PageTabs value={tab} onChange={(v) => setTab(v as PaymentTab)} tabs={TABS} />

      <PageTabPanel value={tab} active={tab} className="mt-4">
        {isLoading ? (
          <div className="text-sm text-muted-foreground py-8">Loading payments…</div>
        ) : isError ? (
          <div className="text-sm text-destructive py-8">Could not load payments.</div>
        ) : tabPayments.length === 0 ? (
          <EmptyState
            title={`No ${tab} payments`}
            hint="Processed invoices with due dates create payment rows automatically."
          />
        ) : (
          <div className="space-y-2.5">
            {tabPayments.map((payment) => (
              <PaymentRow
                key={payment.id}
                payment={payment}
                justPaid={justPaidId === payment.id}
                paymentsExecutionEnabled={paymentsExecutionEnabled}
                manualExecutionEnabled={manualExecutionEnabled}
                approveBusy={approvingId === payment.id}
                onSubmit={() => void advance(payment, "awaiting")}
                onApprove={() => void handleApprovePayment(payment)}
                onPayNow={() => void advance(payment, "paid")}
                onReceipt={() => setReceipt(payment)}
              />
            ))}
          </div>
        )}
      </PageTabPanel>

      <PaymentReceiptSheet
        open={!!receipt}
        onClose={() => setReceipt(null)}
        payment={receipt}
      />
    </div>
  );
}
