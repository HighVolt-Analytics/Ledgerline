import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { SignupPlanSelector } from "@/components/signup/SignupPlanSelector";
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
  getSignupDisabledReason,
  signupPlanHint,
  signupPrimaryCtaLabel,
  type SignupFormFields,
} from "@/lib/signupForm";
import { cn } from "@/lib/cn";

const ENTERPRISE_MAILTO =
  "mailto:sales@ledgerline.com?subject=Enterprise%20plan%20inquiry";

export function SetupPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [form, setForm] = useState<SignupFormFields>(EMPTY_SIGNUP_FIELDS);
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [countryCode, setCountryCode] = useState("AU");
  const [selectedPlan, setSelectedPlan] = useState<PlanId>("free");
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

  const validationInput = useMemo(
    () => ({
      fields: form,
      industry,
      countryCode,
      selectedPlan,
      platformBillingEnabled,
      billingPlansLoading,
      busy,
    }),
    [
      billingPlansLoading,
      busy,
      countryCode,
      form,
      industry,
      platformBillingEnabled,
      selectedPlan,
    ]
  );

  const disabledReason = getSignupDisabledReason(validationInput);
  const canSubmit = disabledReason === null;
  const planHint = signupPlanHint(selectedPlan);

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
        } else if (checkout === "cancelled" || status.status === "expired") {
          setError("Checkout was cancelled. Review your details and try again.");
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

  async function createOrg(event: React.FormEvent) {
    event.preventDefault();

    const submitReason = getSignupDisabledReason(validationInput);
    if (submitReason) {
      setError(submitReason);
      return;
    }

    if (selectedPlan === "enterprise") {
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
        plan_code: selectedPlan === "studio" ? "studio" : "free",
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
      <div className="signup-page__inner">
        <div className="signup-page__brand">
          <LogoBlock />
        </div>

        <header className="signup-page__header">
          <h1>Create your account</h1>
          <p>
            Register your organisation and choose a plan. No invite required.
          </p>
        </header>

        <form className="signup-page__layout" onSubmit={(event) => void createOrg(event)} noValidate>
          <section
            className="signup-page__section"
            aria-labelledby="signup-details-heading"
          >
            <div className="signup-page__card">
              <h2 id="signup-details-heading" className="signup-page__card-title">
                Organisation details
              </h2>

              <div className="signup-page__form">
                <div className="signup-page__field signup-page__field--full">
                  <label className="signup-page__label" htmlFor="setup-business-name">
                    Business name
                  </label>
                  <Input
                    id="setup-business-name"
                    name="businessName"
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
                    name="email"
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
                      name="phone"
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
                    name="password"
                    type="password"
                    placeholder="At least 8 characters"
                    value={form.password}
                    onChange={(event) => updateField("password", event.target.value)}
                    autoComplete="new-password"
                  />
                </div>

                <div className="signup-page__field">
                  <label
                    className="signup-page__label"
                    htmlFor="setup-confirm-password"
                  >
                    Confirm password
                  </label>
                  <Input
                    id="setup-confirm-password"
                    name="confirmPassword"
                    type="password"
                    placeholder="Re-enter password"
                    value={form.confirmPassword}
                    onChange={(event) => updateField("confirmPassword", event.target.value)}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            </div>
          </section>

          <section
            className="signup-page__section signup-page__section--plans"
            aria-labelledby="signup-plan-heading"
          >
            <h2 id="signup-plan-heading" className="signup-page__section-title">
              Choose your plan
            </h2>
            {billingPlansError ? (
              <p className="signup-page__billing-warning" role="status">
                {billingPlansError}
              </p>
            ) : null}
            <SignupPlanSelector
              region={pricingRegion}
              selectedPlan={selectedPlan}
              busy={busy}
              onSelectPlan={setSelectedPlan}
            />
          </section>

          <section className="signup-page__cta">
            {planHint ? (
              <p className="signup-page__plan-hint" data-testid="signup-plan-hint">
                {planHint}
              </p>
            ) : null}

            {message ? (
              <p className="signup-page__message" role="status">
                {message}
              </p>
            ) : null}

            {error ? (
              <p className="signup-page__error" role="alert">
                {error}
              </p>
            ) : null}

            <Button
              type="submit"
              data-testid="button-create-org"
              className="signup-page__submit"
              disabled={!canSubmit}
            >
              {signupPrimaryCtaLabel(selectedPlan, busy)}
            </Button>

            {!canSubmit && disabledReason ? (
              <p
                className="signup-page__disabled-reason"
                data-testid="signup-disabled-reason"
                role="status"
              >
                {disabledReason}
              </p>
            ) : null}

            <p className="signup-page__signin">
              Already have an account?{" "}
              <Link to="/login" className="signup-page__signin-link">
                Sign in
              </Link>
            </p>
          </section>
        </form>

        <p className="signup-page__footer">
          SOC 2 Type II · ISO 27001 · Bank-level encryption
        </p>
      </div>
    </div>
  );
}
