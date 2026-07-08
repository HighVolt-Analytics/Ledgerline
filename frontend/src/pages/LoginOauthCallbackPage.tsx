import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { LogoBlock } from "@/components/Logo";
import { Card } from "@/components/ui/card";
import { PageLoader } from "@/components/PageLoader";
import { setAuthToken, setAuthUser } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { hydrateUserAndMemberships } from "@/lib/authHydrate";
import { persistAuthSuccess } from "@/lib/authSession";
import { completeMicrosoftOAuthInBrowser, loadMicrosoftOAuthConfig } from "@/lib/oauthApi";
import { withRouterBasename } from "@/lib/routerBasename";
import { persistSignupToken } from "@/lib/signupApi";

export function LoginOauthCallbackPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user, loading } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const handled = useRef(false);

  useEffect(() => {
    if (loading || handled.current) return;
    if (user && user.id > 0) {
      navigate("/settings", { replace: true });
      return;
    }

    const err = searchParams.get("error");
    if (err) {
      handled.current = true;
      setError(
        err === "no_account"
          ? "No account found for this email. Please sign up first."
          : "Sign-in failed. Please try again."
      );
      return;
    }

    const signupToken = searchParams.get("signup_token");
    if (signupToken) {
      handled.current = true;
      persistSignupToken(signupToken);
      navigate(`/signup?token=${encodeURIComponent(signupToken)}`, { replace: true });
      return;
    }

    const accessToken = searchParams.get("access_token");
    const refreshToken = searchParams.get("refresh_token");
    if (accessToken && refreshToken) {
      handled.current = true;
      void finishOAuthSession(accessToken, refreshToken).catch(() =>
        setError("Sign-in failed. Please try again.")
      );
      return;
    }

    const tenantSelectToken = searchParams.get("tenant_select_token");
    if (tenantSelectToken) {
      handled.current = true;
      navigate(`/login?oauth_tenant_select=1`, {
        replace: true,
        state: { tenantSelectToken },
      });
      return;
    }

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const provider = searchParams.get("provider");
    const isMicrosoftCallback =
      code &&
      state &&
      (provider === "microsoft" ||
        loadMicrosoftOAuthConfig() !== null ||
        oauthProviderFromState(state) === "microsoft");

    if (isMicrosoftCallback) {
      handled.current = true;
      if (import.meta.env.DEV) {
        console.info("[oauth] callback: Microsoft path", {
          provider,
          hasSessionConfig: loadMicrosoftOAuthConfig() !== null,
          stateProvider: oauthProviderFromState(state!),
        });
      }
      void completeMicrosoftOAuthInBrowser(code!, state!)
        .then(async (result) => {
          if (result.result === "login" && result.access_token && result.refresh_token) {
            await finishOAuthSession(result.access_token, result.refresh_token);
            return;
          }
          if (result.result === "signup" && result.signup_token) {
            persistSignupToken(result.signup_token);
            window.location.replace(
              withRouterBasename(`/signup?token=${encodeURIComponent(result.signup_token)}`)
            );
            return;
          }
          if (result.result === "tenant_select" && result.tenant_select_token) {
            navigate(`/login?oauth_tenant_select=1`, {
              replace: true,
              state: {
                tenantSelectToken: result.tenant_select_token,
                accounts: result.accounts,
              },
            });
            return;
          }
          setError(
            result.error === "no_account"
              ? "No account found for this email. Please sign up first."
              : "Sign-in failed. Please try again."
          );
        })
        .catch((err) => {
          const message = err instanceof Error ? err.message : "Microsoft sign-in failed";
          console.error("[oauth] callback Microsoft failed", err);
          setError(
            import.meta.env.DEV
              ? message
              : "Microsoft sign-in failed. Please try again."
          );
        });
      return;
    }

    handled.current = true;
    if (import.meta.env.DEV) {
      console.warn("[oauth] callback: unrecognized params", {
        keys: [...searchParams.keys()],
        hasCode: Boolean(code),
        hasState: Boolean(state),
        provider,
      });
    }
    setError("Invalid OAuth callback. Please try signing in again.");
  }, [loading, user, navigate, searchParams]);

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md p-6 space-y-4 text-center">
        <LogoBlock />
        {error ? (
          <>
            <p className="text-sm text-destructive">{error}</p>
            <Link to="/login" className="text-sm text-primary hover:underline">
              Back to sign in
            </Link>
          </>
        ) : (
          <PageLoader label="Completing sign-in…" />
        )}
      </Card>
    </div>
  );
}

async function finishOAuthSession(accessToken: string, refreshToken: string) {
  setAuthToken(accessToken);
  const { user, memberships } = await hydrateUserAndMemberships({
    access: accessToken,
    fetchMemberships: "if-empty",
    fallbackToTokenOnMeFailure: true,
  });
  persistAuthSuccess({
    access_token: accessToken,
    refresh_token: refreshToken,
    user,
    memberships,
  });
  setAuthUser(user);
  window.location.replace(withRouterBasename("/settings"));
}

function oauthProviderFromState(state: string): string | null {
  try {
    const segment = state.split(".")[1];
    if (!segment) return null;
    const padded = segment.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(padded)) as { provider?: string };
    return payload.provider ?? null;
  } catch {
    return null;
  }
}
