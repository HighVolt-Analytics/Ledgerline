import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { SignupPlanStep } from "@/components/signup/SignupPlanStep";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { selectClassMd } from "@/lib/selectClass";
import {
  COUNTRIES,
  INDUSTRIES,
  countryByCode,
  type Industry,
} from "@/data/orgSetup.tsx";
import { pricingRegionForCountry, type PlanId } from "@/lib/pricingPlans";
import {
  EMPTY_SIGNUP_FIELDS,
  getAccountDetailsDisabledReason,
  getPlanActionDisabledReason,
  type SignupFormFields,
} from "@/lib/signupForm";
import { cn } from "@/lib/cn";

const ENTERPRISE_MAILTO =
  "mailto:sales@ledgerline.com?subject=Enterprise%20plan%20inquiry";

type SignupStep = "details" | "plan";

export function SetupPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [step, setStep] = useState<SignupStep>("details");
  const [form, setForm] = useState<SignupFormFields>(EMPTY_SIGNUP_FIELDS);
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [countryCode, setCountryCode] = useState("AU");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [platformBillingEnabled, setPlatformBillingEnabled] = useState<boolean | null>(
    null
  );
  const [billingPlansLoading, setBillingPlansLoading] = useState(true);
  const [billingPlansError, setBillingPlansError] = useState<string | null>(null);

  const country = countryByCode(countryCode);
  const pricingRegion = pricingRegionForCountry(countryCode);

  const updateField = <K extends keyof SignupFormFields>(key: K, value: SignupFormFields[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const planValidationBase = useMemo(
    () => ({
      fields: form,
      industry,
      countryCode,
      platformBillingEnabled,
      billingPlansLoading,
      busy,
    }),
    [billingPlansLoading, busy, countryCode, form, industry, platformBillingEnabled]
  );

  const detailsDisabledReason = getAccountDetailsDisabledReason(
    form,
    industry,
    countryCode,
    busy
  );
  const canContinueDetails = detailsDisabledReason === null;

  const planDisabledReason = (plan: PlanId) =>
    getPlanActionDisabledReason(plan, planValidationBase);

  useEffect(() => {
    let cancelled = false;
    setBillingPlansLoading(true);
    setBillingPlansError(null);

    void api
      .getPublicBillingPlans(countryCode)
      .then((catalog) => {
        if (cancelled) return;
        setPlatformBillingEnabled(catalog.platform_billing_enabled === true);
      })
      .catch((err) => {
        if (cancelled) return;
        setPlatformBillingEnabled(null);
        setBillingPlansError(
          err instanceof Error ? err.message : "Could not load billing configuration"
        );
      })
      .finally(() => {
        if (!cancelled) setBillingPlansLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [countryCode]);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    const sessionId = searchParams.get("session_id");
    if (!checkout || !sessionId) return;

    void (async () => {
      try {
        const status = await api.getSignupCheckoutStatus(sessionId);
        if (checkout === "success" && status.payment_status === "paid") {
          setMessage(
            "Payment successful — your organisation is ready. Sign in to continue."
          );
          setStep("plan");
        } else if (checkout === "cancelled" || status.status === "expired") {
          setError("Checkout was cancelled. Choose a plan to try again.");
          setStep("plan");
        } else if (checkout === "success") {
          setMessage("Payment received — finishing account setup…");
          setStep("plan");
        }
      } catch {
        if (checkout === "success") {
          setMessage("Payment submitted — sign in shortly once setup completes.");
          setStep("plan");
        }
      } finally {
        setSearchParams({}, { replace: true });
      }
    })();
  }, [searchParams, setSearchParams]);

  function continueToPlans(event: React.FormEvent) {
    event.preventDefault();
    const reason = getAccountDetailsDisabledReason(form, industry, countryCode, busy);
    if (reason) {
      setError(reason);
      return;
    }
    setError(null);
    setStep("plan");
  }

  async function submitSignup(plan: PlanId) {
    const reason = getPlanActionDisabledReason(plan, planValidationBase);
    if (reason) {
      setError(reason);
      return;
    }

    if (plan === "enterprise") {
      window.location.href = ENTERPRISE_MAILTO;
      return;
    }

    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.createSignupCheckout({
        email: form.email.trim(),
        password: form.password,
        organisation_name: form.businessName.trim(),
        country: countryCode,
        plan_code: plan === "studio" ? "studio" : "free",
        industry,
        full_name: form.businessName.trim(),
        signup_source: "public",
      });

      if (result.checkout_url) {
        window.location.href = result.checkout_url;
        return;
      }

      navigate("/login", {
        replace: true,
        state: {
          email: form.email.trim(),
          fromSignup: true,
          signupMessage: "Your free account is ready. Sign in to get started.",
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signup-page">
      <div className="signup-page__inner signup-page__inner--wizard">
        <div className="signup-page__brand">
          <LogoBlock />
        </div>

        <header className="signup-page__header">
          <p className="signup-page__step-label">Step {step === "details" ? 1 : 2} of 2</p>
          <h1>{step === "details" ? "Create your account" : "Choose your plan"}</h1>
          <p>
            {step === "details"
              ? "Enter your organisation and sign-in details."
              : "Pick the plan that fits your team. No invite required."}
          </p>
        </header>

        {message ? (
          <p className="signup-page__message signup-page__message--banner" role="status">
            {message}
          </p>
        ) : null}

        {error ? (
          <p className="signup-page__error signup-page__error--banner" role="alert">
            {error}
          </p>
        ) : null}

        {step === "details" ? (
          <form
            className="signup-page__wizard-card"
            onSubmit={continueToPlans}
            noValidate
          >
            <div className="signup-page__form signup-page__form--single">
              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-business-name">
                  Business name
                </label>
                <Input
                  id="setup-business-name"
                  data-testid="input-business-name"
                  placeholder="Enter your business name"
                  value={form.businessName}
                  onChange={(event) => updateField("businessName", event.target.value)}
                  autoComplete="organization"
                />
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-industry">
                  Industry
                </label>
                <Select
                  id="setup-industry"
                  data-testid="select-industry"
                  value={industry}
                  onValueChange={(value) => setIndustry(value as Industry)}
                  size="md"
                  options={INDUSTRIES.map((ind) => ({ value: ind, label: ind }))}
                  className="w-full"
                />
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-country">
                  Country
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
                <p className="signup-page__hint tnum">
                  {country.currency} {country.symbol} · {country.taxLabel}{" "}
                  {country.taxRate}%
                </p>
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-email">
                  Email
                </label>
                <Input
                  id="setup-email"
                  type="email"
                  data-testid="input-email"
                  placeholder="Enter your work email"
                  value={form.email}
                  onChange={(event) => updateField("email", event.target.value)}
                  autoComplete="email"
                />
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-phone">
                  Phone
                </label>
                <div className="signup-page__phone">
                  <span
                    className={cn(
                      selectClassMd,
                      "signup-page__dial-code text-muted-foreground"
                    )}
                  >
                    {country.dialCode}
                  </span>
                  <Input
                    id="setup-phone"
                    type="tel"
                    data-testid="input-phone"
                    placeholder="Enter phone number"
                    value={form.phone}
                    onChange={(event) => updateField("phone", event.target.value)}
                    autoComplete="tel-national"
                  />
                </div>
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-password">
                  Password
                </label>
                <Input
                  id="setup-password"
                  type="password"
                  placeholder="At least 8 characters"
                  value={form.password}
                  onChange={(event) => updateField("password", event.target.value)}
                  autoComplete="new-password"
                />
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-confirm-password">
                  Confirm password
                </label>
                <Input
                  id="setup-confirm-password"
                  type="password"
                  placeholder="Re-enter password"
                  value={form.confirmPassword}
                  onChange={(event) => updateField("confirmPassword", event.target.value)}
                  autoComplete="new-password"
                />
              </div>
            </div>

            <div className="signup-page__wizard-actions">
              <Button
                type="submit"
                data-testid="button-continue-details"
                className="signup-page__submit"
                disabled={!canContinueDetails}
              >
                Continue
              </Button>
              {!canContinueDetails && detailsDisabledReason ? (
                <p
                  className="signup-page__disabled-reason"
                  data-testid="signup-disabled-reason"
                  role="status"
                >
                  {detailsDisabledReason}
                </p>
              ) : null}
            </div>
          </form>
        ) : (
          <section className="signup-page__wizard-card signup-page__wizard-card--plans">
            {billingPlansError ? (
              <p className="signup-page__billing-warning" role="status">
                {billingPlansError}
              </p>
            ) : null}
            <SignupPlanStep
              region={pricingRegion}
              busy={busy}
              planDisabledReason={planDisabledReason}
              onChoosePlan={(plan) => void submitSignup(plan)}
            />
            <div className="signup-page__wizard-actions">
              <Button
                type="button"
                variant="outline"
                data-testid="button-back-details"
                onClick={() => {
                  setError(null);
                  setStep("details");
                }}
                disabled={busy}
              >
                Back to account details
              </Button>
            </div>
          </section>
        )}

        <p className="signup-page__signin signup-page__signin--footer">
          Already have an account?{" "}
          <Link to="/login" className="signup-page__signin-link">
            Sign in
          </Link>
        </p>

        <p className="signup-page__footer">
          SOC 2 Type II · ISO 27001 · Bank-level encryption
        </p>
      </div>
    </div>
  );
}
