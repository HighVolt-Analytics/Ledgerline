import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { setAuthToken, setAuthUser } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { persistAuthSuccess } from "@/lib/authSession";
import { homePathForRole } from "@/lib/roles";
import { withRouterBasename } from "@/lib/routerBasename";
import {
  apiPortalEmbedLogin,
  superAdminPortalHomePath,
} from "@/lib/superAdminPortalEmbed";

type Status = "loading" | "error";

export function SuperAdminEmbedPage() {
  const { user, loading: authLoading } = useAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const accessToken = params.get("accessToken")?.trim();
    if (!accessToken) {
      setStatus("error");
      setError("Missing access token.");
      return;
    }

    let cancelled = false;

    void (async () => {
      try {
        const data = await apiPortalEmbedLogin(accessToken);
        if (cancelled) return;

        persistAuthSuccess({
          access_token: data.access_token,
          refresh_token: data.refresh_token,
          user: data.user,
          memberships: data.memberships,
        });
        setAuthToken(data.access_token);
        setAuthUser(data.user);
        window.location.assign(superAdminPortalHomePath());
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setError(err instanceof Error ? err.message : "Could not sign in.");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (!authLoading && user) {
    return <Navigate to={homePathForRole(user.role)} replace />;
  }

  if (status === "error") {
    return (
      <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm text-destructive">{error ?? "Sign-in failed."}</p>
        <a href={withRouterBasename("/login")} className="text-sm text-primary underline">
          Go to login
        </a>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center text-muted-foreground text-sm">
      Signing in to super admin portal…
    </div>
  );
}
