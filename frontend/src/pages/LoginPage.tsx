import { useEffect, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { AuthCenteredCard } from "@/components/auth/AuthCenteredCard";
import { OAuthBrandIcon } from "@/components/auth/OAuthBrandIcon";
import { useAuth } from "@/context/AuthContext";
import { postLoginPathForRole, readReturnTo, rememberOAuthReturnTo } from "@/lib/authReturnTo";
import { PUBLIC_SIGNUP_PATH } from "@/lib/publicSignupRoutes";
import { withRouterBasename } from "@/lib/routerBasename";
import { fetchOAuthProviders, startGoogleOAuth, startMicrosoftOAuth } from "@/lib/oauthApi";
import { apiFetchTenantSelectAccounts, apiSelectTenant, type TenantAccountSummary } from "@/lib/authApi";
import { persistAuthSuccess } from "@/lib/authSession";
import { setAuthToken, setAuthUser } from "@/api/client";
import { Eye, EyeOff } from "lucide-react";

type Step = "credentials" | "otp" | "pick-tenant";

export function LoginPage() {
  const location = useLocation();
  const signupMessage =
    location.state &&
    typeof location.state === "object" &&
    "signupMessage" in location.state &&
    typeof location.state.signupMessage === "string"
      ? location.state.signupMessage
      : null;

  const {
    user,
    loading,
    login,
    verifyOtp,
    selectTenant,
    resendOtp,
    tenantPicker,
  } = useAuth();

  const [step, setStep] = useState<Step>("credentials");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState(() => {
    const state = location.state;
    if (
      state &&
      typeof state === "object" &&
      "email" in state &&
      typeof state.email === "string"
    ) {
      return state.email;
    }
    return "";
  });
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [oauthProviders, setOauthProviders] = useState({ google: false, microsoft: false });
  const [oauthTenantSelect, setOauthTenantSelect] = useState(false);
  const [oauthAccounts, setOauthAccounts] = useState<TenantAccountSummary[]>([]);
  const [oauthSelectToken, setOauthSelectToken] = useState<string | null>(null);
  const [oauthAccountsLoading, setOauthAccountsLoading] = useState(false);
  const returnTo = readReturnTo(new URLSearchParams(location.search));

  useEffect(() => {
    rememberOAuthReturnTo(returnTo);
  }, [returnTo]);

  useEffect(() => {
    void fetchOAuthProviders()
      .then((p) => setOauthProviders({ google: p.google, microsoft: p.microsoft }))
      .catch(() => setOauthProviders({ google: false, microsoft: false }));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("oauth_tenant_select") !== "1") return;

    setStep("pick-tenant");
    setOauthTenantSelect(true);
    const state = location.state as {
      tenantSelectToken?: string;
      accounts?: TenantAccountSummary[];
    } | null;
    const token = state?.tenantSelectToken ?? null;
    if (token) setOauthSelectToken(token);
    if (state?.accounts?.length) {
      setOauthAccounts(state.accounts);
      return;
    }
    if (!token) return;

    let cancelled = false;
    setOauthAccountsLoading(true);
    void apiFetchTenantSelectAccounts(token)
      .then((accounts) => {
        if (!cancelled) setOauthAccounts(accounts);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load organisations");
        }
      })
      .finally(() => {
        if (!cancelled) setOauthAccountsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [location]);

  if (!loading && user && user.id > 0) {
    return <Navigate to={postLoginPathForRole(user.role, returnTo)} replace />;
  }

  async function onCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      setStep("otp");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function onOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await verifyOtp(otp);
      if (result === "pick-tenant") setStep("pick-tenant");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function onPickTenant(tenantId: string) {
    setError(null);
    setBusy(true);
    try {
      if (oauthTenantSelect && oauthSelectToken) {
        const result = await apiSelectTenant(oauthSelectToken, tenantId);
        persistAuthSuccess({
          access_token: result.access_token,
          refresh_token: result.refresh_token,
          user: result.user,
          memberships: result.memberships,
        });
        setAuthToken(result.access_token);
        setAuthUser(result.user);
        window.location.replace(
          withRouterBasename(postLoginPathForRole(result.user.role, returnTo))
        );
        return;
      }
      await selectTenant(tenantId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not select tenant");
    } finally {
      setBusy(false);
    }
  }

  const pickerAccounts =
    oauthTenantSelect && oauthAccounts.length > 0 ? oauthAccounts : tenantPicker;

  return (
    <AuthCenteredCard
      title={
        step === "credentials"
          ? "Sign in to Ledgerline"
          : step === "otp"
            ? "Verify your email"
            : "Choose organisation"
      }
      subtitle={
        step === "credentials"
          ? "Welcome to a workspace that's secure, powerful, and totally private."
          : step === "otp"
            ? "Enter the verification code sent to your email (dev: 123456)"
            : "Select which organisation to open"
      }
    >
      {loading && (
        <div className="auth-form" aria-busy="true" aria-label="Loading">
          <div className="auth-skeleton auth-skeleton-title" />
          <div className="auth-skeleton auth-skeleton-subtitle" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-input" />
          <div className="auth-skeleton auth-skeleton-button" />
          <div className="flex flex-col gap-3 mt-6">
            <div className="auth-skeleton auth-skeleton-line w-32" />
            <div className="auth-skeleton auth-skeleton-line w-48" />
          </div>
        </div>
      )}

      {!loading && step === "credentials" && (
        <form onSubmit={onCredentials} className="auth-form">
          {signupMessage ? (
            <p className="auth-success" role="status">
              {signupMessage}
            </p>
          ) : null}
          <input
            type="email"
            className="auth-input"
            placeholder="Email or username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
          <div className="auth-input-wrap">
            <input
              type={showPassword ? "text" : "password"}
              className="auth-input"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
            <button
              type="button"
              className="auth-input-toggle"
              aria-label={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword((v) => !v)}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? "Please wait…" : "Log in"}
          </button>

          {(oauthProviders.google || oauthProviders.microsoft) && (
            <div className="auth-oauth">
              <p className="auth-oauth-label">or continue with</p>
              <div className="auth-oauth-row">
                {oauthProviders.microsoft && (
                  <button
                    type="button"
                    className="auth-oauth-btn"
                    disabled={busy}
                    onClick={() => void startMicrosoftOAuth("login")}
                  >
                    <OAuthBrandIcon provider="microsoft" />
                    <span>Microsoft</span>
                  </button>
                )}
                {oauthProviders.google && (
                  <button
                    type="button"
                    className="auth-oauth-btn"
                    disabled={busy}
                    onClick={() => startGoogleOAuth("login")}
                  >
                    <OAuthBrandIcon provider="google" />
                    <span>Google</span>
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="auth-footer">
            <Link to="/forgot-password" className="auth-link">
              Forgot password?
            </Link>
            <p>
              Don&apos;t have an account?{" "}
              <Link to={PUBLIC_SIGNUP_PATH} className="auth-link-accent">
                Create an account
              </Link>
            </p>
          </div>
        </form>
      )}

      {!loading && step === "otp" && (
        <form onSubmit={onOtp} className="auth-form">
          <input
            className="auth-input"
            placeholder="6-digit code"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            required
            inputMode="numeric"
            autoComplete="one-time-code"
          />
          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? "Verifying…" : "Verify"}
          </button>
          <button
            type="button"
            className="auth-secondary-btn"
            disabled={busy}
            onClick={() => void resendOtp().catch((e) => setError(String(e)))}
          >
            Resend code
          </button>
        </form>
      )}

      {!loading && step === "pick-tenant" && (
        <div className="auth-form">
          {oauthAccountsLoading ? (
            <p className="text-sm text-muted-foreground text-center">Loading organisations…</p>
          ) : null}
          {pickerAccounts.map((t) => (
            <button
              key={t.tenant_id}
              type="button"
              className="auth-tenant-btn"
              disabled={busy}
              onClick={() => void onPickTenant(t.tenant_id)}
            >
              <span>{t.tenant_name}</span>
              <span className="auth-tenant-role">{t.role.replace(/_/g, " ")}</span>
            </button>
          ))}
          {error ? (
            <p className="auth-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </AuthCenteredCard>
  );
}
