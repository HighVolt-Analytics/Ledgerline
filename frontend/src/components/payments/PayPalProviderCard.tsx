import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  useConnectPayPal,
  useDisconnectPayPal,
  usePayPalBalance,
  usePayPalReadiness,
  usePayPalTransactions,
  useRefreshPayPalReadiness,
} from "@/hooks/usePayPal";
import type { PaypalReadinessResponse } from "@/api/types";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { useState } from "react";

function formatCapabilityReason(reason: string | null | undefined): string {
  const code = (reason || "").toLowerCase();
  if (code === "paypal_not_configured") {
    return "PayPal is not configured for this environment.";
  }
  if (code === "paypal_reporting_access_required") {
    return "Balance reporting requires PayPal reporting access. This is not available yet.";
  }
  if (!reason) return "Not available with the current PayPal connection.";
  return reason.replaceAll("_", " ");
}

function formatLastError(
  lastError: PaypalReadinessResponse["last_error"]
): string | null {
  if (!lastError) return null;
  if (typeof lastError === "string") return lastError;
  return lastError.message || lastError.code || null;
}

function maskMerchantId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 6)}…${id.slice(-4)}`;
}

export function paypalPayoutsReady(
  readiness: PaypalReadinessResponse | null | undefined
): boolean {
  return Boolean(readiness?.connected && readiness?.payouts_enabled);
}

export type PayProvider = "stripe" | "paypal";

export function PayProviderSelector({
  value,
  onChange,
  paypalEnabled,
  disabled = false,
  paymentId,
}: {
  value: PayProvider;
  onChange: (next: PayProvider) => void;
  paypalEnabled: boolean;
  disabled?: boolean;
  paymentId?: string;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-1.5 text-xs"
      data-testid={paymentId ? `pay-provider-selector-${paymentId}` : "pay-provider-selector"}
    >
      <span className="text-muted-foreground mr-1">Pay with:</span>
      <Button
        type="button"
        size="sm"
        variant={value === "stripe" ? "default" : "outline"}
        className="h-7 text-xs"
        disabled={disabled}
        onClick={() => onChange("stripe")}
        data-testid={paymentId ? `button-pay-provider-stripe-${paymentId}` : "button-pay-provider-stripe"}
      >
        Stripe
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "paypal" ? "default" : "outline"}
        className="h-7 text-xs"
        disabled={disabled || !paypalEnabled}
        title={
          paypalEnabled
            ? "Pay with connected PayPal"
            : "Connect PayPal and enable payouts to use this option"
        }
        onClick={() => onChange("paypal")}
        data-testid={
          paymentId ? `button-pay-provider-paypal-${paymentId}` : "button-pay-provider-paypal"
        }
      >
        PayPal
      </Button>
    </div>
  );
}

export function PayPalProviderCard() {
  const { data: readiness, isLoading: readinessLoading } = usePayPalReadiness();
  const connected = Boolean(readiness?.connected);
  const { data: balance, isLoading: balanceLoading } = usePayPalBalance(connected);
  const { data: transactionsPayload, isLoading: transactionsLoading } =
    usePayPalTransactions(10, connected);
  const connectPayPal = useConnectPayPal();
  const disconnectPayPal = useDisconnectPayPal();
  const refreshReadiness = useRefreshPayPalReadiness();
  const [actionError, setActionError] = useState<string | null>(null);

  const busy =
    connectPayPal.isPending ||
    disconnectPayPal.isPending ||
    refreshReadiness.isPending;

  const handleConnect = async () => {
    setActionError(null);
    try {
      const result = await connectPayPal.mutateAsync();
      const url = result.onboarding_url || result.redirect_url;
      if (url) {
        window.location.href = url;
        return;
      }
      await refreshReadiness.mutateAsync();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Unable to connect PayPal");
    }
  };

  const handleVerify = async () => {
    setActionError(null);
    try {
      await refreshReadiness.mutateAsync();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Unable to refresh PayPal status"
      );
    }
  };

  const handleDisconnect = async () => {
    const confirmed = window.confirm(
      "Disconnect this PayPal account from LedgerLink? You can reconnect after this."
    );
    if (!confirmed) return;

    setActionError(null);
    try {
      await disconnectPayPal.mutateAsync();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Unable to disconnect PayPal account"
      );
    }
  };

  const lastError = formatLastError(readiness?.last_error ?? null);
  const balanceUnavailable = connected && balance && !balance.available;
  const transactionsUnavailable =
    connected && transactionsPayload && !transactionsPayload.available;

  return (
    <Card className="p-4" data-testid="card-paypal-connect">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
        <div className="flex items-start gap-2.5">
          <Link2 className="h-4 w-4 text-primary mt-0.5 shrink-0" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-medium">PayPal</h2>
              <span
                className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                data-testid="badge-paypal-status"
              >
                {!readiness?.configured
                  ? "Not configured"
                  : connected
                    ? readiness.payouts_enabled
                      ? "Connected"
                      : "Connected · payouts off"
                    : "Not connected"}
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Connect a PayPal business account for tenant payouts. Stripe workflow stays
              unchanged.
            </p>
          </div>
        </div>
        {connected ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleVerify()}
              disabled={busy}
              data-testid="button-verify-paypal"
            >
              {refreshReadiness.isPending ? "Verifying…" : "Verify"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleDisconnect()}
              disabled={busy}
              data-testid="button-disconnect-paypal"
            >
              {disconnectPayPal.isPending ? "Disconnecting…" : "Disconnect"}
            </Button>
          </div>
        ) : null}
      </div>

      {actionError ? (
        <p className="text-xs text-destructive mb-3">{actionError}</p>
      ) : null}

      {readiness?.needs_reauthorization ? (
        <div
          className="rounded-md border ds-warning-panel border px-3 py-2 text-xs mb-3 ds-warning-text"
          data-testid="paypal-reauth-banner"
        >
          PayPal needs reauthorization. Reconnect to restore payouts.
        </div>
      ) : null}

      {lastError ? (
        <p className="text-xs text-muted-foreground mb-3">Last error: {lastError}</p>
      ) : null}

      {readinessLoading ? (
        <p className="text-xs text-muted-foreground">Loading PayPal connection…</p>
      ) : !connected ? (
        <div className="space-y-3">
          <div
            className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
            data-testid="paypal-not-connected-message"
          >
            {readiness?.configured
              ? "Connect PayPal to view readiness, balance, and payout capability."
              : "PayPal is not configured on the server yet."}
          </div>
          <Button
            size="sm"
            onClick={() => void handleConnect()}
            disabled={busy || readiness?.configured === false}
            data-testid="button-connect-paypal"
          >
            {connectPayPal.isPending ? "Connecting…" : "Connect PayPal"}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 text-xs">
            <div>
              <span className="text-muted-foreground">Merchant</span>
              <div className="font-mono text-foreground">
                {readiness?.merchant_id
                  ? maskMerchantId(readiness.merchant_id)
                  : readiness?.display_name || "—"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Onboarding</span>
              <div className="text-foreground">
                {readiness?.onboarding_complete ? "Complete" : "Incomplete"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Payments</span>
              <div className="text-foreground">
                {readiness?.payments_enabled ? "Enabled" : "Disabled"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Payouts</span>
              <div
                className="text-foreground"
                data-testid="paypal-payouts-status"
              >
                {readiness?.payouts_enabled ? "Enabled" : "Disabled"}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground">Last verified</span>
              <div className="text-foreground">
                {readiness?.last_verified_at
                  ? new Date(readiness.last_verified_at).toLocaleString()
                  : "—"}
              </div>
            </div>
          </div>

          <div
            className={cn(
              "rounded-md border px-3 py-2 text-xs",
              balanceUnavailable
                ? "border-border bg-muted/40 text-muted-foreground"
                : "border-border/60 bg-muted/30"
            )}
            data-testid="paypal-balance-panel"
          >
            {balanceLoading ? (
              <span className="text-muted-foreground">Loading balance…</span>
            ) : balanceUnavailable ? (
              <span data-testid="paypal-balance-unavailable">
                {formatCapabilityReason(balance?.reason)}
              </span>
            ) : balance?.balances?.length ? (
              <div className="space-y-1 tnum">
                {balance.balances.map((row, index) => (
                  <div key={`${row.currency ?? "cur"}-${index}`}>
                    {row.currency ?? "—"}: available{" "}
                    {row.available != null
                      ? money(Number(row.available), row.currency)
                      : "—"}
                    {row.total != null
                      ? ` · total ${money(Number(row.total), row.currency)}`
                      : ""}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-muted-foreground">No balance rows returned.</span>
            )}
          </div>

          <div>
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              Recent PayPal transactions
            </h3>
            {transactionsUnavailable ? (
              <div
                className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
                data-testid="paypal-transactions-unavailable"
              >
                {formatCapabilityReason(transactionsPayload?.reason)}
              </div>
            ) : (
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm" data-testid="table-paypal-transactions">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground border-b border-border">
                      <th className="px-3 py-2 font-medium">When</th>
                      <th className="px-3 py-2 font-medium">Type</th>
                      <th className="px-3 py-2 font-medium">Recipient</th>
                      <th className="px-3 py-2 font-medium text-right">Amount</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactionsLoading ? (
                      <tr>
                        <td
                          colSpan={5}
                          className="px-3 py-6 text-center text-muted-foreground"
                        >
                          Loading transactions…
                        </td>
                      </tr>
                    ) : !(transactionsPayload?.transactions?.length) ? (
                      <tr>
                        <td
                          colSpan={5}
                          className="px-3 py-6 text-center text-muted-foreground"
                        >
                          No PayPal transactions yet.
                        </td>
                      </tr>
                    ) : (
                      transactionsPayload.transactions.map((txn) => (
                        <tr
                          key={txn.id}
                          className="border-b border-border/60 last:border-0 hover-elevate"
                        >
                          <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                            {txn.occurred_at
                              ? new Date(txn.occurred_at).toLocaleDateString()
                              : "—"}
                          </td>
                          <td className="px-3 py-2 text-xs">
                            {txn.transaction_type ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">
                            {txn.recipient ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-xs text-right tnum whitespace-nowrap">
                            {txn.gross_amount != null
                              ? money(Number(txn.gross_amount), txn.currency)
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
            )}
          </div>

          <div
            className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs flex flex-wrap items-center justify-between gap-2"
            data-testid="paypal-pay-capability"
          >
            <span className="text-muted-foreground">
              Payable payouts via PayPal require connection and payouts enabled.
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-xs pointer-events-none"
              disabled={!paypalPayoutsReady(readiness)}
              tabIndex={-1}
              aria-disabled={!paypalPayoutsReady(readiness)}
              data-testid="button-paypal-pay-capability"
            >
              {paypalPayoutsReady(readiness) ? "Payouts ready" : "Payouts not enabled"}
            </Button>
          </div>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground mt-3 border-t border-border/60 pt-3">
        PayPal is used for tenant-owned connected payouts. Balance and transaction history
        appear only when PayPal reporting access is available.
      </p>
    </Card>
  );
}
