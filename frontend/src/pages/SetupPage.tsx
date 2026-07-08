import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { PricingPlanCards } from "@/components/billing/PricingPlanCards";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { selectClassMd } from "@/lib/selectClass";
import {
  COUNTRIES,
  INDUSTRIES,
  countryByCode,
  vaultPreview,
  type Industry,
} from "@/data/orgSetup.tsx";
import { pricingRegionForCountry, type PlanId } from "@/lib/pricingPlans";
import { cn } from "@/lib/cn";

export function SetupPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [countryCode, setCountryCode] = useState("AU");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [selectedPlan, setSelectedPlan] = useState<PlanId>("free");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const country = countryByCode(countryCode);
  const preview = vaultPreview(industry);
  const pricingRegion = pricingRegionForCountry(countryCode);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    const sessionId = searchParams.get("session_id");
    if (!checkout || !sessionId) return;

    void (async () => {
      try {
        const status = await api.getSignupCheckoutStatus(sessionId);
        if (checkout === "success" && status.payment_status === "paid") {
          setMessage("Payment successful — your organisation is ready. Sign in to continue.");
        } else if (checkout === "cancelled" || status.status === "expired") {
          setError("Checkout was cancelled. Choose a plan to try again.");
        } else if (checkout === "success") {
          setMessage("Payment received — finishing account setup…");
        }
      } catch {
        if (checkout === "success") {
          setMessage("Payment submitted — sign in shortly once setup completes.");
        }
      } finally {
        setSearchParams({}, { replace: true });
      }
    })();
  }, [searchParams, setSearchParams]);

  function goToSignIn() {
    navigate("/login", { replace: true });
  }

  async function createOrg() {
    if (!businessName.trim()) {
      setError("Business name is required.");
      return;
    }
    if (!email.trim()) {
      setError("Email is required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (selectedPlan === "enterprise") {
      window.location.href = "mailto:sales@ledgerline.com?subject=Enterprise%20plan";
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.createSignupCheckout({
        email: email.trim(),
        password,
        organisation_name: businessName.trim(),
        country: countryCode,
        plan_code: selectedPlan === "studio" ? "studio" : "free",
        industry,
        full_name: businessName.trim(),
      });

      if (result.checkout_url) {
        window.location.href = result.checkout_url;
        return;
      }

      setMessage("Organisation created. Sign in to get started.");
      navigate("/login", {
        replace: true,
        state: { email: email.trim(), fromSignup: true },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create organisation");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center bg-background px-4 py-8">
      <div className="mb-8">
        <LogoBlock />
      </div>

      <div className="w-full max-w-3xl rounded-xl border border-border bg-card p-8 shadow-lg">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight">Set up your organisation</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Choose your country and plan. Pricing and credits are set from your business country.
          </p>
        </div>

        <div className="space-y-5">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="setup-business-name">
              Business name
            </label>
            <Input
              id="setup-business-name"
              data-testid="input-business-name"
              placeholder="Acme Pty Ltd"
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-industry">
                Industry
              </label>
              <Select
                id="setup-industry"
                data-testid="select-industry"
                value={industry}
                onValueChange={(v) => setIndustry(v as Industry)}
                size="md"
                options={INDUSTRIES.map((ind) => ({ value: ind, label: ind }))}
                className="w-full"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-country">
                Business country
              </label>
              <Select
                id="setup-country"
                data-testid="select-country"
                value={countryCode}
                onValueChange={setCountryCode}
                size="md"
                options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground tnum">
                {country.currency} {country.symbol} · {country.taxLabel} {country.taxRate}%
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-email">
                Email
              </label>
              <Input
                id="setup-email"
                type="email"
                data-testid="input-email"
                placeholder="accounts@acme.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-phone">
                Phone
              </label>
              <div className="flex gap-2">
                <span
                  className={cn(
                    selectClassMd,
                    "w-14 shrink-0 flex items-center justify-center text-muted-foreground px-2"
                  )}
                >
                  {country.dialCode}
                </span>
                <Input
                  id="setup-phone"
                  type="tel"
                  data-testid="input-phone"
                  placeholder="400 000 000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-password">
                Password
              </label>
              <Input
                id="setup-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-confirm-password">
                Confirm password
              </label>
              <Input
                id="setup-confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
          </div>

          <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Vault preview · {industry}:</span>{" "}
            {preview}…
          </div>

          <div>
            <h2 className="text-sm font-semibold mb-3">Choose your plan</h2>
            <PricingPlanCards
              region={pricingRegion}
              currentPlan={selectedPlan}
              canUpgradeStudio
              allowFreeSelect
              busy={busy}
              onSelectPlan={setSelectedPlan}
            />
            <p className="text-xs text-muted-foreground mt-2">
              Selected: <span className="font-medium capitalize">{selectedPlan}</span>
              {selectedPlan === "studio" && " — you will complete payment on Stripe Checkout."}
            </p>
          </div>

          {message && (
            <p className="text-sm text-[hsl(var(--chart-1))]" role="status">
              {message}
            </p>
          )}
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <button
              type="button"
              data-testid="link-use-sample"
              className="text-sm text-primary hover:underline underline-offset-2"
              onClick={goToSignIn}
            >
              Already have an account? Sign in
            </button>
            <Button
              data-testid="button-create-org"
              onClick={() => void createOrg()}
              disabled={busy || !businessName.trim() || !email.trim()}
            >
              {busy
                ? "Working…"
                : selectedPlan === "studio"
                  ? "Continue to Stripe Checkout"
                  : "Create organisation"}
            </Button>
          </div>
        </div>
      </div>

      <p className="mt-6 text-[11px] text-muted-foreground">
        SOC 2 Type II · ISO 27001 · Bank-level encryption
      </p>
    </div>
  );
}
