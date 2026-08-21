import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SignupPlanStep } from "@/components/signup/SignupPlanStep";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { selectClassMd } from "@/lib/selectClass";
import { setAuthToken, setAuthUser } from "@/api/client";
import { persistAuthSuccess } from "@/lib/authSession";
import { hydrateUserAndMemberships } from "@/lib/authHydrate";
import { withRouterBasename } from "@/lib/routerBasename";
import {
  INDUSTRIES,
  type Industry,
} from "@/data/orgSetup.tsx";
import { useSetupCatalogs } from "@/hooks/useSetupCatalogs";
import { pricingRegionForCountry, type PlanId } from "@/lib/pricingPlans";
import {
  EMPTY_SIGNUP_FIELDS,
  getIdentityDisabledReason,
  getOrganizationDisabledReason,
  getPlanActionDisabledReason,
  type SignupFormFields,
} from "@/lib/signupForm";
import { cn } from "@/lib/cn";
import { fetchOAuthProviders, startGoogleOAuth, startMicrosoftOAuth } from "@/lib/oauthApi";
import { api } from "@/api/client";
import {
  clearSignupToken,
  fetchSignupSession,
  getSignupToken,
  persistSignupToken,
  signupCheckout,
  signupCompleteFree,
  signupCompleteStudio,
  signupRegister,
  signupSelectPlan,
  signupSetOrganization,
  signupVerifyOtp,
} from "@/lib/signupApi";

const ENTERPRISE_MAILTO =
  "mailto:sales@ledgerline.com?subject=Enterprise%20plan%20inquiry";

type WizardStep = "identity" | "otp" | "organization" | "plan" | "confirming";

const STEP_NUMBER: Record<WizardStep, number> = {
  identity: 1,
  otp: 1,
  organization: 2,
  plan: 3,
  confirming: 3,
};

export function SetupPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [step, setStep] = useState<WizardStep>("identity");
  const [signupToken, setSignupToken] = useState<string | null>(getSignupToken());
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [identityViaOAuth, setIdentityViaOAuth] = useState(false);
  const [oauthProviders, setOauthProviders] = useState({ google: false, microsoft: false });

  const [form, setForm] = useState<SignupFormFields>(EMPTY_SIGNUP_FIELDS);
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [countryCode, setCountryCode] = useState("");
  const [currencyCode, setCurrencyCode] = useState("");
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [otp, setOtp] = useState("");
  const { countries, currencies } = useSetupCatalogs();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [platformBillingEnabled, setPlatformBillingEnabled] = useState<boolean | null>(null);
  const [billingPlansLoading, setBillingPlansLoading] = useState(true);
  const [billingPlansError, setBillingPlansError] = useState<string | null>(null);

  const provisionStarted = useRef(false);
  const studioCheckoutActive = useRef(false);
  const studioCompleteStarted = useRef<string | null>(null);
  const [confirmingMode, setConfirmingMode] = useState<"free" | "studio" | null>(null);
  const country =
    countries.find((c) => c.code === countryCode) ?? {
      code: countryCode,
      name: countryCode || "Select country",
      defaultCurrency: "",
      locale: "",
      taxRate: null as number | null,
      taxLabel: "Tax",
      dialCode: "",
    };
  const selectedCurrency =
    currencies.find((c) => c.code === currencyCode) ?? {
      code: currencyCode,
      name: currencyCode || "Select currency",
      symbol: "",
      decimalPlaces: 2,
    };
  const pricingRegion = pricingRegionForCountry(countryCode);

  const planValidationBase = useMemo(
    () => ({
      fields: form,
      industry,
      countryCode,
      currencyCode,
      currencyCodes: currencies.map((c) => c.code),
      countryCodes: countries.map((c) => c.code),
      platformBillingEnabled,
      billingPlansLoading,
      busy,
    }),
    [
      billingPlansLoading,
      busy,
      countries,
      countryCode,
      currencies,
      currencyCode,
      form,
      industry,
      platformBillingEnabled,
    ]
  );

  const updateField = <K extends keyof SignupFormFields>(key: K, value: SignupFormFields[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const identityDisabledReason = getIdentityDisabledReason(form, busy);
  const organizationDisabledReason = getOrganizationDisabledReason(
    form,
    industry,
    countryCode,
    currencyCode,
    busy,
    {
      countryCodes: countries.map((c) => c.code),
      currencyCodes: currencies.map((c) => c.code),
    }
  );
  const planDisabledReason = (plan: PlanId) => getPlanActionDisabledReason(plan, planValidationBase);

  useEffect(() => {
    void fetchOAuthProviders()
      .then((p) => setOauthProviders({ google: p.google, microsoft: p.microsoft }))
      .catch(() => setOauthProviders({ google: false, microsoft: false }));
  }, []);

  useEffect(() => {
    const tokenFromUrl = searchParams.get("signup_token");
    if (tokenFromUrl) {
      persistSignupToken(tokenFromUrl);
      setSignupToken(tokenFromUrl);
    }
  }, [searchParams]);

  useEffect(() => {
    if (!signupToken) return;
    void fetchSignupSession(signupToken)
      .then((session) => {
        setForm((current) => ({
          ...current,
          email: session.email,
          businessName: session.organization_name ?? current.businessName,
          phone: session.phone ?? current.phone,
        }));
        setIdentityViaOAuth(session.identity_via_oauth);
        if (session.country) {
          setCountryCode(session.country);
          const match = countries.find((c) => c.code === session.country);
          if (!currencyTouched) {
            setCurrencyCode(
              session.currency || match?.defaultCurrency || ""
            );
          }
        }
        if (session.currency) setCurrencyCode(session.currency);
        if (session.industry) setIndustry(session.industry as Industry);
        setStep((current) => {
          if (current === "confirming" || studioCheckoutActive.current) return current;
          if (session.status === "payment" || session.status === "provisioning") {
            return "confirming";
          }
          if (session.status === "plan") return "plan";
          if (session.status === "organization" || session.identity_via_oauth) {
            return "organization";
          }
          return current;
        });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Invalid signup session"));
  }, [signupToken]);

  useEffect(() => {
    if (step !== "plan" && step !== "organization") return;

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
  }, [countryCode, step]);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    const sessionId = searchParams.get("session_id");
    if (!checkout || !sessionId || !signupToken) return;

    studioCheckoutActive.current = true;
    setStep("confirming");
    setConfirmingMode("studio");
    setSearchParams({}, { replace: true });

    if (checkout === "cancelled") {
      setError("Checkout was cancelled. Choose a plan to try again.");
      setStep("plan");
      return;
    }

    if (checkout === "success") {
      if (studioCompleteStarted.current === sessionId) return;
      studioCompleteStarted.current = sessionId;
      void finishStudioCheckout(signupToken, sessionId);
    }
  }, [searchParams, setSearchParams, signupToken]);

  useEffect(() => {
    if (step !== "confirming" || !signupToken || provisionStarted.current) return;
    if (confirmingMode !== "free") return;

    provisionStarted.current = true;
    setBusy(true);
    setError(null);
    void signupCompleteFree(signupToken)
      .then((result) => finishAuthAndRedirect(result))
      .catch((err) => {
        provisionStarted.current = false;
        setError(err instanceof Error ? err.message : "Could not complete signup");
        setStep("plan");
      })
      .finally(() => setBusy(false));
  }, [step, signupToken, confirmingMode]);

  async function finishStudioCheckout(token: string, sessionId: string) {
    setBusy(true);
    setError(null);
    setMessage("Payment received — finishing account setup…");

    const maxAttempts = 12;
    try {
      for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        try {
          const result = await signupCompleteStudio(token, sessionId);
          studioCheckoutActive.current = false;
          await finishAuthAndRedirect(result);
          return;
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Could not complete signup";
          if (msg.includes("still processing") && attempt < maxAttempts - 1) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            continue;
          }
          setError(msg);
          setMessage(null);
          return;
        }
      }
    } finally {
      setBusy(false);
    }
  }

  async function finishAuthAndRedirect(result: {
    access_token: string;
    refresh_token: string;
    redirect_to?: string;
    user: { id: number; role: string };
  }) {
    setAuthToken(result.access_token);
    const { user, memberships } = await hydrateUserAndMemberships({
      access: result.access_token,
      fetchMemberships: "always",
      fallbackToTokenOnMeFailure: true,
    });
    persistAuthSuccess({
      access_token: result.access_token,
      refresh_token: result.refresh_token,
      user,
      memberships,
    });
    setAuthUser(user);
    clearSignupToken();
    window.location.replace(withRouterBasename(result.redirect_to || "/settings"));
  }

  async function onEmailRegister(e: React.FormEvent) {
    e.preventDefault();
    const reason = getIdentityDisabledReason(form, busy);
    if (reason) {
      setError(reason);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await signupRegister(form.email, form.password, "");
      setChallengeToken(result.challenge_token);
      setStep("otp");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function onVerifyOtp(e: React.FormEvent) {
    e.preventDefault();
    if (!challengeToken) return;
    setBusy(true);
    setError(null);
    try {
      const result = await signupVerifyOtp(challengeToken, otp);
      persistSignupToken(result.signup_token);
      setSignupToken(result.signup_token);
      setStep("organization");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function onOrganization(e: React.FormEvent) {
    e.preventDefault();
    if (!signupToken) {
      setError("Sign-in session expired — please start again.");
      setStep("identity");
      return;
    }
    const reason = getOrganizationDisabledReason(
      form,
      industry,
      countryCode,
      currencyCode,
      busy,
      {
        countryCodes: countries.map((c) => c.code),
        currencyCodes: currencies.map((c) => c.code),
      }
    );
    if (reason) {
      setError(reason);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signupSetOrganization(
        signupToken,
        form.businessName.trim(),
        countryCode,
        currencyCode,
        industry,
        form.phone.trim()
      );
      setStep("plan");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save organisation");
    } finally {
      setBusy(false);
    }
  }

  async function onChoosePlan(plan: PlanId) {
    if (!signupToken) {
      setError("Sign-in session expired — please start again.");
      setStep("identity");
      return;
    }
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
      await signupSelectPlan(signupToken, plan === "studio" ? "studio" : "free");
      if (plan === "studio") {
        const checkout = await signupCheckout(signupToken);
        window.location.href = checkout.checkout_url;
        return;
      }
      provisionStarted.current = false;
      setConfirmingMode("free");
      setStep("confirming");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select plan");
    } finally {
      setBusy(false);
    }
  }

  const stepLabel = STEP_NUMBER[step];
  const title =
    step === "identity" || step === "otp"
      ? "Create your account"
      : step === "organization"
        ? "Your organisation"
        : step === "plan"
          ? "Choose your plan"
          : "Setting up your workspace";

  const subtitle =
    step === "identity"
      ? "Sign up with Microsoft, Google, or your work email."
      : step === "otp"
        ? "Enter the verification code sent to your email."
        : step === "organization"
          ? "Tell us about your business — pricing depends on country."
          : step === "plan"
            ? "Pick the plan that fits your team."
            : "Provisioning your tenant…";

  return (
    <div className="signup-page">
      <div className="signup-page__inner signup-page__inner--wizard">
        <div className="signup-page__brand">
          <LogoBlock />
        </div>

        <header className="signup-page__header">
          <p className="signup-page__step-label">Step {stepLabel} of 3</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
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

        {(step === "identity" || step === "otp") && (
          <div className="signup-page__wizard-card space-y-4">
            {step === "identity" && (
              <>
                {(oauthProviders.google || oauthProviders.microsoft) && (
                  <div className="space-y-2">
                    {oauthProviders.microsoft && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full"
                        disabled={busy}
                        onClick={() => void startMicrosoftOAuth("signup")}
                      >
                        Continue with Microsoft
                      </Button>
                    )}
                    {oauthProviders.google && (
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full"
                        disabled={busy}
                        onClick={() => startGoogleOAuth("signup")}
                      >
                        Continue with Google
                      </Button>
                    )}
                    <p className="text-center text-xs text-muted-foreground">or sign up with email</p>
                  </div>
                )}

                <form onSubmit={onEmailRegister} className="signup-page__form signup-page__form--single">
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
                  <div className="signup-page__wizard-actions">
                    <Button
                      type="submit"
                      data-testid="button-continue-identity"
                      className="signup-page__submit"
                      disabled={Boolean(identityDisabledReason)}
                    >
                      Continue
                    </Button>
                    {identityDisabledReason ? (
                      <p className="signup-page__disabled-reason" role="status">
                        {identityDisabledReason}
                      </p>
                    ) : null}
                  </div>
                </form>
              </>
            )}

            {step === "otp" && (
              <form onSubmit={onVerifyOtp} className="signup-page__form signup-page__form--single">
                <Input
                  placeholder="6-digit code"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  required
                  inputMode="numeric"
                  autoComplete="one-time-code"
                />
                <Button type="submit" className="signup-page__submit w-full" disabled={busy}>
                  Verify email
                </Button>
              </form>
            )}
          </div>
        )}

        {step === "organization" && (
          <form
            className="signup-page__wizard-card"
            onSubmit={onOrganization}
            noValidate
          >
            {identityViaOAuth && form.email ? (
              <p className="signup-page__hint mb-2">
                Signed in as <span className="font-medium text-foreground">{form.email}</span>
              </p>
            ) : null}
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
                  onValueChange={(code) => {
                    setCountryCode(code);
                    if (!currencyTouched) {
                      const match = countries.find((c) => c.code === code);
                      setCurrencyCode(match?.defaultCurrency || currencyCode);
                    }
                  }}
                  size="md"
                  searchable
                  options={countries.map((c) => ({ value: c.code, label: c.name }))}
                  className="w-full"
                />
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-currency">
                  Currency
                </label>
                <Select
                  id="setup-currency"
                  data-testid="select-currency"
                  value={currencyCode}
                  onValueChange={(code) => {
                    setCurrencyTouched(true);
                    setCurrencyCode(code);
                  }}
                  size="md"
                  searchable
                  options={currencies.map((c) => ({
                    value: c.code,
                    label: `${c.code}${c.symbol ? ` (${c.symbol})` : ""} — ${c.name}`,
                  }))}
                  className="w-full"
                />
                <p className="signup-page__hint tnum">
                  {selectedCurrency.code}
                  {selectedCurrency.symbol ? ` ${selectedCurrency.symbol}` : ""} ·{" "}
                  {country.taxLabel}
                  {country.taxRate != null ? ` ${country.taxRate}%` : ""}
                </p>
              </div>

              <div className="signup-page__field">
                <label className="signup-page__label" htmlFor="setup-phone">
                  Phone
                </label>
                <div className="signup-page__phone">
                  {country.dialCode ? (
                    <span
                      className={cn(
                        selectClassMd,
                        "signup-page__dial-code text-muted-foreground"
                      )}
                    >
                      {country.dialCode}
                    </span>
                  ) : null}
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
            </div>

            <div className="signup-page__wizard-actions">
              <Button
                type="submit"
                data-testid="button-continue-details"
                className="signup-page__submit"
                disabled={Boolean(organizationDisabledReason)}
              >
                Continue to plans
              </Button>
              {organizationDisabledReason ? (
                <p className="signup-page__disabled-reason" data-testid="signup-disabled-reason" role="status">
                  {organizationDisabledReason}
                </p>
              ) : null}
            </div>
          </form>
        )}

        {step === "plan" && (
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
              onChoosePlan={(plan) => void onChoosePlan(plan)}
            />
            <div className="signup-page__wizard-actions">
              <Button
                type="button"
                variant="outline"
                data-testid="button-back-details"
                onClick={() => {
                  setError(null);
                  setStep("organization");
                }}
                disabled={busy}
              >
                Back to organisation details
              </Button>
            </div>
          </section>
        )}

        {step === "confirming" && (
          <div className="signup-page__wizard-card text-center text-sm text-muted-foreground py-8">
            {busy ? "Creating your organisation and signing you in…" : error || "Please wait…"}
          </div>
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
