import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Coins, Mail, MessageCircle, X } from "lucide-react";
import { ManagePlanDialog } from "@/components/billing/ManagePlanDialog";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NumericInput } from "@/components/ui/numeric-input";
import { useAuth } from "@/context/AuthContext";
import { useBilling, useBillingMutations, useBillingUsage } from "@/hooks/useBilling";
import { usePricingRegion } from "@/hooks/usePricingRegion";
import { api } from "@/api/client";
import { countryByCode } from "@/data/orgSetup";
import { cn } from "@/lib/cn";
import type { PlanId } from "@/lib/pricingPlans";

function planLabel(plan: string) {
  if (plan === "studio") return "Studio";
  if (plan === "enterprise") return "Enterprise";
  return "Free";
}

function formatEventType(type: string) {
  return type.replace(/_/g, " ");
}

export function BillingPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: billing, isLoading, error, refetch } = useBilling(Boolean(user));
  const [usagePage, setUsagePage] = useState(1);
  const { data: usage } = useBillingUsage(usagePage, Boolean(user && billing));
  const { topUp, upgradeToStudio } = useBillingMutations();
  const [institutionCountry, setInstitutionCountry] = useState<string | null>(null);
  const { region: pricingRegion } = usePricingRegion({
    tenantCountry: billing?.plan_info?.region,
    institutionCountry,
  });

  useEffect(() => {
    if (!user) return;
    api
      .getInstitutionSettings()
      .then((inst) => setInstitutionCountry(inst.country))
      .catch(() => {
        /* optional */
      });
  }, [user]);

  const [manageOpen, setManageOpen] = useState(false);
  const [topUpOpen, setTopUpOpen] = useState(false);
  const [topUpAmount, setTopUpAmount] = useState<number | undefined>(50);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    const sessionId = searchParams.get("session_id");
    if (!checkout || !sessionId || !user) return;

    void (async () => {
      try {
        const status = await api.getCheckoutStatus(sessionId);
        if (checkout === "success" && status.payment_status === "paid") {
          setMessage("Payment successful — your credits will update shortly.");
        } else if (checkout === "cancelled" || status.status === "expired") {
          setMessage("Checkout was cancelled.");
        } else if (checkout === "success") {
          setMessage("Payment received — confirming with Stripe…");
        }
        await refetch();
      } catch {
        if (checkout === "success") {
          setMessage("Payment submitted — refresh shortly if credits are not visible yet.");
        }
      } finally {
        setSearchParams({}, { replace: true });
      }
    })();
  }, [searchParams, setSearchParams, user, refetch]);

  if (!user) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Processing credits for your organisation." />
        <p className="text-sm text-muted-foreground">Sign in to manage billing.</p>
      </div>
    );
  }

  if (isLoading && !billing) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Processing credits for your organisation." />
        <PageLoader label="Loading billing…" />
      </div>
    );
  }

  if (error || !billing || !billing.plan_info) {
    return (
      <div>
        <PageHeader title="Billing & Credits" subtitle="Processing credits for your organisation." />
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load billing"}
        </p>
      </div>
    );
  }

  const planInfo = billing.plan_info;
  const country = countryByCode(planInfo.region);
  const symbol = country.symbol;
  const platformBilling = billing.platform_billing_enabled === true;
  const topUpCredits =
    topUpAmount != null ? Math.floor(topUpAmount * planInfo.topup_factor) : 0;

  async function handleTopUp() {
    if (topUpAmount == null || topUpAmount <= 0) return;
    setBusy(true);
    setMessage(null);
    try {
      if (platformBilling) {
        const session = await api.createTopUpCheckout(topUpAmount);
        if (session.checkout_url) {
          window.location.href = session.checkout_url;
          return;
        }
        throw new Error("Stripe checkout URL was not returned");
      }
      await topUp(topUpAmount);
      setMessage("Top-up successful — credits added to your balance.");
      setTopUpOpen(false);
      await refetch();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Top-up failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpgrade() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await upgradeToStudio();
      if (result && "checkout_url" in result && result.checkout_url) {
        window.location.href = result.checkout_url;
        return;
      }
      setMessage("Upgraded to Studio — full monthly credits applied.");
      setManageOpen(false);
      await refetch();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Upgrade failed");
    } finally {
      setBusy(false);
    }
  }

  async function handlePlanSelect(plan: PlanId) {
    if (plan !== "studio") return;
    await handleUpgrade();
  }

  return (
    <div>
      <PageHeader
        title="Billing & Credits"
        subtitle="Pay-as-you-go processing credits based on document pages."
        actions={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setManageOpen(true)}>
              Manage plan
            </Button>
            {billing.can_top_up && (
              <Button onClick={() => setTopUpOpen(true)}>Top up</Button>
            )}
          </div>
        }
      />

      {message && (
        <p className="mb-4 text-sm text-[hsl(var(--chart-1))]">{message}</p>
      )}

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <Card className="p-5 lg:col-span-1 bg-gradient-to-br from-primary/8 to-transparent border-primary/20">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
            <Coins className="h-4 w-4 text-primary" />
            Credit balance
          </div>
          <p className="text-3xl font-semibold tnum" data-testid="text-credit-balance">
            {billing.balance.toLocaleString()}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Plan: <span className="font-medium">{planLabel(billing.plan)}</span>
            {" · "}
            {billing.credits_consumed.toLocaleString()} consumed
          </p>
          {billing.fy_days_remaining != null && (
            <p className="text-xs text-muted-foreground mt-2">
              {billing.fy_days_remaining} days left in current credit year
            </p>
          )}
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h2 className="text-sm font-semibold mb-3">Credit usage</h2>
          <ul className="space-y-2">
            <li className="flex items-center justify-between text-sm py-1.5 border-b border-border">
              <span>Per page processed</span>
              <span className="tnum text-muted-foreground">
                {billing.credits_per_page} credits
              </span>
            </li>
            <li className="flex items-center justify-between text-sm py-1.5 border-b border-border">
              <span>Monthly allowance ({planLabel(billing.plan)})</span>
              <span className="tnum text-muted-foreground">
                {planInfo.monthly_credits.toLocaleString()} credits
              </span>
            </li>
            <li className="flex items-center justify-between text-sm py-1.5 border-b border-border">
              <span>User seats</span>
              <span className="tnum text-muted-foreground">
                up to {planInfo.max_users}
              </span>
            </li>
            <li className="flex items-center justify-between text-sm py-1.5">
              <span className="flex items-center gap-2">
                <MessageCircle className="h-3.5 w-3.5" /> Social ·{" "}
                <Mail className="h-3.5 w-3.5" /> Email
              </span>
              <span className="text-muted-foreground text-xs">
                {planInfo.social_integration && planInfo.email_integration
                  ? "Included"
                  : "Upgrade to Studio"}
              </span>
            </li>
          </ul>
        </Card>
      </div>

      <h2 className="text-sm font-semibold mb-3">Usage history</h2>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-left">
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-4 py-2 font-medium">Event</th>
                <th className="px-4 py-2 font-medium">Detail</th>
                <th className="px-4 py-2 font-medium text-right">Credits</th>
                <th className="px-4 py-2 font-medium text-right">Balance</th>
              </tr>
            </thead>
            <tbody>
              {(usage?.items ?? []).map((row) => (
                <tr key={row.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                    {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2.5 capitalize">{formatEventType(row.event_type)}</td>
                  <td className="px-4 py-2.5 text-muted-foreground max-w-xs truncate">
                    {row.description}
                    {row.pages != null && row.pages > 0 && (
                      <span className="ml-1">({row.pages} pg)</span>
                    )}
                  </td>
                  <td
                    className={cn(
                      "px-4 py-2.5 text-right tnum",
                      row.credits_delta < 0 ? "text-destructive" : "text-[hsl(var(--chart-1))]"
                    )}
                  >
                    {row.credits_delta > 0 ? "+" : ""}
                    {row.credits_delta.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right tnum">{row.balance_after.toLocaleString()}</td>
                </tr>
              ))}
              {(usage?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No usage recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {usage && usage.pages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              disabled={usagePage <= 1}
              onClick={() => setUsagePage((p) => Math.max(1, p - 1))}
            >
              Previous
            </Button>
            <span className="text-xs text-muted-foreground">
              Page {usage.page} of {usage.pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={usagePage >= usage.pages}
              onClick={() => setUsagePage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        )}
      </Card>

      <ManagePlanDialog
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        currentPlan={billing.plan as PlanId}
        currentPlanLabel={planLabel(billing.plan)}
        region={pricingRegion}
        canUpgradeStudio={billing.can_upgrade_studio}
        busy={busy}
        platformBillingEnabled={platformBilling}
        onSelectPlan={(plan) => void handlePlanSelect(plan)}
      />

      {topUpOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Top up credits</h3>
              <button type="button" onClick={() => setTopUpOpen(false)} aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-sm text-muted-foreground">
              Enter amount in {country.currency}.
              {platformBilling
                ? " You will be redirected to Stripe Checkout to complete payment."
                : " Credits are added instantly (demo payment)."}
            </p>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">{symbol}</span>
              <NumericInput
                value={topUpAmount}
                onValueChange={setTopUpAmount}
                className="flex-1"
              />
            </div>
            <p className="text-sm">
              You will receive{" "}
              <span className="font-semibold tnum">{topUpCredits.toLocaleString()}</span> credits
            </p>
            <Button className="w-full" disabled={busy || !topUpAmount} onClick={() => void handleTopUp()}>
              {platformBilling
                ? `Pay ${symbol}${topUpAmount?.toLocaleString() ?? "0"} with Stripe`
                : `Pay ${symbol}${topUpAmount?.toLocaleString() ?? "0"} (simulated)`}
            </Button>
          </Card>
        </div>
      )}
    </div>
  );
}
