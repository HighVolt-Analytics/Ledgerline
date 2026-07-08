import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { setAuthToken, setAuthUser } from "@/api/client";
import { persistAuthSuccess } from "@/lib/authSession";
import { hydrateUserAndMemberships } from "@/lib/authHydrate";
import { withRouterBasename } from "@/lib/routerBasename";
import {
  clearSignupToken,
  fetchSignupPlans,
  fetchSignupSession,
  getSignupToken,
  persistSignupToken,
  signupCheckout,
  signupCompleteFree,
  signupConfirmPayment,
  signupRegister,
  signupSelectPlan,
  signupSetOrganization,
  signupVerifyOtp,
  type SignupPlan,
} from "@/lib/signupApi";
import { fetchOAuthProviders, startGoogleOAuth, startMicrosoftOAuth } from "@/lib/oauthApi";
import { COUNTRIES, countryByCode } from "@/lib/settingsData";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";

type Step = "identity" | "otp" | "organization" | "plan" | "confirming";

export function SignupPage() {
  const [searchParams] = useSearchParams();
  const { user, loading } = useAuth();

  const [step, setStep] = useState<Step>("identity");
  const [signupToken, setSignupToken] = useState<string | null>(getSignupToken());
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [otp, setOtp] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [country, setCountry] = useState("AU");
  const [plans, setPlans] = useState<SignupPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<string>("free");
  const [identityViaOAuth, setIdentityViaOAuth] = useState(false);
  const [oauthProviders, setOauthProviders] = useState({ google: false, microsoft: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const provisionStarted = useRef(false);

  useEffect(() => {
    void fetchOAuthProviders()
      .then(setOauthProviders)
      .catch(() => setOauthProviders({ google: false, microsoft: false }));
  }, []);

  useEffect(() => {
    const tokenFromUrl = searchParams.get("token");
    if (tokenFromUrl) {
      persistSignupToken(tokenFromUrl);
      setSignupToken(tokenFromUrl);
    }
    const stepParam = searchParams.get("step");
    if (stepParam === "confirming") {
      setStep("confirming");
    }
  }, [searchParams]);

  useEffect(() => {
    if (!signupToken) return;
    void fetchSignupSession(signupToken)
      .then((session) => {
        setEmail(session.email);
        setFullName(session.full_name);
        setIdentityViaOAuth(session.identity_via_oauth);
        if (session.organization_name) setOrganizationName(session.organization_name);
        if (session.country) setCountry(session.country);
        if (session.plan) setSelectedPlan(session.plan);
        if (session.status === "payment" || session.status === "provisioning") {
          setStep("confirming");
        } else if (session.status === "plan") {
          setStep("plan");
        } else if (session.identity_via_oauth || session.status === "organization") {
          setStep("organization");
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Invalid signup session"));
  }, [signupToken]);

  useEffect(() => {
    if (step !== "plan" || !signupToken) return;
    setPlansLoading(true);
    setError(null);
    void fetchSignupPlans(signupToken)
      .then(setPlans)
      .catch((err) => {
        setPlans([]);
        setError(err instanceof Error ? err.message : "Could not load plans");
      })
      .finally(() => setPlansLoading(false));
  }, [step, signupToken]);

  useEffect(() => {
    if (step !== "confirming" || !signupToken || provisionStarted.current) return;
    provisionStarted.current = true;
    const sessionId = searchParams.get("session_id");
    setBusy(true);
    setError(null);

    const run = async () => {
      try {
        let result;
        if (sessionId) {
          result = await signupConfirmPayment(signupToken, sessionId);
        } else {
          result = await signupCompleteFree(signupToken);
        }
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
      } catch (err) {
        provisionStarted.current = false;
        setError(err instanceof Error ? err.message : "Could not complete signup");
        setStep("plan");
      } finally {
        setBusy(false);
      }
    };
    void run();
  }, [step, signupToken, searchParams]);

  if (!loading && user && user.id > 0) {
    return <Navigate to="/settings" replace />;
  }

  async function onRegister(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await signupRegister(email, password, fullName);
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
    if (!signupToken) return;
    setBusy(true);
    setError(null);
    try {
      await signupSetOrganization(signupToken, organizationName, country);
      setStep("plan");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save organisation");
    } finally {
      setBusy(false);
    }
  }

  async function onSelectPlan(plan: string) {
    if (!signupToken) return;
    setBusy(true);
    setError(null);
    setSelectedPlan(plan);
    try {
      await signupSelectPlan(signupToken, plan);
      if (plan === "free") {
        setStep("confirming");
        return;
      }
      const checkout = await signupCheckout(signupToken);
      window.location.href = checkout.checkout_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select plan");
    } finally {
      setBusy(false);
    }
  }

  const title =
    step === "identity"
      ? "Create your account"
      : step === "otp"
        ? "Verify your email"
        : step === "organization"
          ? "Your organisation"
          : step === "plan"
            ? "Choose a plan"
            : "Setting up your workspace";

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-background px-4 py-8">
      <Card className="w-full max-w-lg p-6 space-y-6">
        <div className="flex justify-center">
          <LogoBlock />
        </div>
        <div className="text-center space-y-1">
          <h1 className="text-xl font-semibold">{title}</h1>
          <p className="text-sm text-muted-foreground">
            {step === "identity"
              ? "Sign up with email or continue with Google / Microsoft"
              : step === "organization"
                ? "This name becomes your organisation and tenant — pricing depends on country"
                : step === "plan"
                  ? "Start free or upgrade to Studio for more credits"
                  : step === "confirming"
                    ? "Provisioning your tenant…"
                    : "Enter the code sent to your email"}
          </p>
        </div>

        {step === "identity" && (
          <div className="space-y-4">
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
            <form onSubmit={onRegister} className="space-y-3">
              <Input
                placeholder="Full name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
              <Input
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <Input
                type="password"
                placeholder="Password (min 8 characters)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? "Please wait…" : "Continue"}
              </Button>
            </form>
            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link to="/login" className="text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        )}

        {step === "otp" && (
          <form onSubmit={onVerifyOtp} className="space-y-3">
            <Input
              placeholder="6-digit code"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              required
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy}>
              Verify
            </Button>
          </form>
        )}

        {step === "organization" && (
          <form onSubmit={onOrganization} className="space-y-3">
            {identityViaOAuth && (
              <p className="text-sm text-muted-foreground">
                Signed in as <span className="font-medium text-foreground">{email}</span>
              </p>
            )}
            <Input
              placeholder="Organisation name"
              value={organizationName}
              onChange={(e) => setOrganizationName(e.target.value)}
              required
            />
            <div className="space-y-1.5">
              <label htmlFor="select-signup-country" className="text-sm font-medium">
                Country
              </label>
              <Select
                id="select-signup-country"
                value={country}
                onValueChange={setCountry}
                size="md"
                options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground">
                Plans are priced in {countryByCode(country).currency} for your region
              </p>
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy || !organizationName.trim()}>
              Continue
            </Button>
          </form>
        )}

        {step === "plan" && (
          <div className="space-y-3">
            {plansLoading && (
              <p className="text-sm text-muted-foreground text-center py-4">Loading plans…</p>
            )}
            {!plansLoading &&
              plans.map((plan) => (
              <button
                key={plan.plan}
                type="button"
                disabled={busy}
                onClick={() => void onSelectPlan(plan.plan)}
                className={cn(
                  "w-full rounded-lg border p-4 text-left transition-colors hover:border-primary",
                  selectedPlan === plan.plan && "border-primary bg-primary/5"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{plan.label}</span>
                  <span className="text-sm tnum">
                    {plan.monthly_price === 0
                      ? "Free"
                      : `${plan.currency_code} ${plan.monthly_price}/mo`}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {plan.monthly_credits.toLocaleString()} credits/mo · up to {plan.max_users} user
                  {plan.max_users === 1 ? "" : "s"}
                </p>
                {plan.plan === "studio" && (
                  <p className="text-xs text-muted-foreground mt-2">
                    Simulated Stripe checkout — no real charge in this environment
                  </p>
                )}
              </button>
            ))}
            {!plansLoading && plans.length === 0 && !error && (
              <p className="text-sm text-muted-foreground text-center py-4">No plans available.</p>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
        )}

        {step === "confirming" && (
          <div className="text-center text-sm text-muted-foreground py-6">
            {busy ? "Creating your organisation and signing you in…" : error || "Please wait…"}
          </div>
        )}
      </Card>
    </div>
  );
}
