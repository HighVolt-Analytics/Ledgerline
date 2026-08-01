import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  api,
  clearGetCache,
  getAuthToken,
  hydrateAuthTokenFromSession,
  setAuthToken,
  setAuthUser,
  setUnauthorizedHandler,
} from "@/api/client";
import type { AuthUser } from "@/api/types";
import {
  apiLogin,
  apiResendOtp,
  apiSelectTenant,
  apiVerifyOtp,
  type TenantAccountSummary,
} from "@/lib/authApi";
import { bootstrapUserFromAccess, hydrateUserAndMemberships } from "@/lib/authHydrate";
import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  persistAuthSuccess,
  persistMemberships,
  PROFILE_UPDATED_EVENT,
  rememberLastTenant,
} from "@/lib/authSession";
import { isTokenExpired, tenantIdFromToken, userFromToken } from "@/lib/authToken";
import { refreshAccessTokenSingleFlight } from "@/lib/authTokenRefresh";
import { shouldApplyAuthSync, subscribeAuthSync } from "@/lib/authSync";
import {
  clearAllTenantCaches,
  endTenantTransition,
  tenantSessionWillChange,
} from "@/lib/tenantSession";
import { postLoginPathForRole, readReturnToFromLocation } from "@/lib/authReturnTo";
import { withRouterBasename } from "@/lib/routerBasename";
import { queryClient } from "@/lib/queryClient";
import { identifyOpenReplayUser } from "@/third-party/sessionRecorder/OpenReplay/OpenReplay";

type SessionCachePolicy = "full" | "soft" | "none";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  verifyOtp: (otp: string) => Promise<"done" | "pick-tenant">;
  selectTenant: (tenantId: string) => Promise<void>;
  resendOtp: () => Promise<void>;
  logout: () => void;
  switchTenant: (tenantId: string) => Promise<void>;
  /** @deprecated Use switchTenant ΓÇö kept for backward compat. */
  switchOrganisation: (tenantId: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  challengeToken: string | null;
  tenantPicker: TenantAccountSummary[];
  tenantSelectToken: string | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function invalidateSessionCaches(policy: SessionCachePolicy) {
  if (policy === "full") {
    queryClient.clear();
    clearGetCache();
  } else if (policy === "soft") {
    clearGetCache();
    void queryClient.invalidateQueries();
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  hydrateAuthTokenFromSession();

  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [tenantSelectToken, setTenantSelectToken] = useState<string | null>(null);
  const [tenantPicker, setTenantPicker] = useState<TenantAccountSummary[]>([]);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (user?.email) {
      identifyOpenReplayUser(user.email, {
        user_id: String(user.id),
        tenant_id: user.tenant_id,
        role: user.role,
      });
    }
  }, [user?.id, user?.email, user?.tenant_id, user?.role]);

  const applySession = useCallback(
    (
      access: string,
      refresh: string,
      profile: AuthUser,
      memberships?: TenantAccountSummary[],
      cachePolicy: SessionCachePolicy = "full"
    ) => {
      // Read previous tenant from in-memory JWT BEFORE any sessionStorage write.
      const previousAccess = getAuthToken();
      const tenantChanged = tenantSessionWillChange(access, previousAccess);
      if (tenantChanged) {
        clearAllTenantCaches();
      }

      persistAuthSuccess({
        access_token: access,
        refresh_token: refresh,
        user: profile,
        memberships,
      });
      setAuthToken(access);
      setAuthUser(profile);
      if (mountedRef.current) {
        setUser(profile);
      }

      const effectiveCachePolicy = tenantChanged ? "full" : cachePolicy;
      invalidateSessionCaches(effectiveCachePolicy);

      // Same-tenant refresh: release any transition lock. Tenant switches hard-reload
      // before paint; if they do not, TenantBoundary keeps the loader up.
      if (!tenantChanged) {
        endTenantTransition();
      }
    },
    []
  );

  const logout = useCallback(() => {
    const refresh = getRefreshToken();
    clearAllTenantCaches();
    clearAuthSession();
    setAuthToken(null);
    setAuthUser(null);
    if (mountedRef.current) {
      setUser(null);
      setChallengeToken(null);
      setTenantSelectToken(null);
      setTenantPicker([]);
    }
    endTenantTransition();
    void api.logout(refresh ?? undefined).catch(() => undefined);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiLogin(email, password);
    setChallengeToken(data.challenge_token);
  }, []);

  const verifyOtp = useCallback(
    async (otp: string) => {
      if (!challengeToken) throw new Error("Login session expired");
      const data = await apiVerifyOtp(challengeToken, otp);
      setChallengeToken(null);
      if (data.multi_tenant && data.tenant_select_token) {
        setTenantSelectToken(data.tenant_select_token);
        setTenantPicker(data.accounts ?? []);
        if (data.accounts?.length) {
          persistMemberships(data.accounts);
        }
        return "pick-tenant" as const;
      }
      if (!data.access_token || !data.refresh_token || !data.user) {
        throw new Error("Invalid login response");
      }
      applySession(data.access_token, data.refresh_token, data.user);
      return "done" as const;
    },
    [applySession, challengeToken]
  );

  // Initial login tenant pick: hard reload so no prior tenant UI can remain mounted.
  const selectTenant = useCallback(
    async (tenantId: string) => {
      if (!tenantSelectToken) throw new Error("Tenant selection expired");
      const data = await apiSelectTenant(tenantSelectToken, tenantId);
      setTenantSelectToken(null);
      setTenantPicker([]);
      applySession(
        data.access_token,
        data.refresh_token,
        data.user,
        data.memberships
      );
      rememberLastTenant(tenantId);
      window.location.replace(
        withRouterBasename(postLoginPathForRole(data.user.role, readReturnToFromLocation()))
      );
    },
    [applySession, tenantSelectToken]
  );

  const resendOtp = useCallback(async () => {
    if (!challengeToken) throw new Error("Login session expired");
    const data = await apiResendOtp(challengeToken);
    setChallengeToken(data.challenge_token);
  }, [challengeToken]);

  // In-app org switch: hard reload so tenant-scoped React state and caches reset fully.
  const switchTenant = useCallback(
    async (tenantId: string) => {
      const data = await api.switchTenant(tenantId);
      applySession(
        data.access_token,
        data.refresh_token,
        data.user,
        data.memberships
      );
      rememberLastTenant(tenantId);
      window.location.replace(
        withRouterBasename(postLoginPathForRole(data.user.role, readReturnToFromLocation()))
      );
    },
    [applySession]
  );

  const refreshUser = useCallback(async () => {
    const access = getAccessToken();
    const refresh = getRefreshToken();
    if (!access || !refresh) return;

    const { user: me, memberships } = await hydrateUserAndMemberships({
      access,
      fetchMemberships: "always",
    });

    if (!mountedRef.current) return;

    setUser(me);
    setAuthUser(me);
    persistAuthSuccess({
      access_token: access,
      refresh_token: refresh,
      user: me,
      memberships,
    });
    invalidateSessionCaches("soft");
    window.dispatchEvent(new CustomEvent(PROFILE_UPDATED_EVENT, { detail: { user: me } }));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      if (!getRefreshToken()) {
        logout();
        return;
      }
      try {
        await refreshAccessTokenSingleFlight();
        if (!mountedRef.current) return;

        const access = getAccessToken();
        const initial = access ? bootstrapUserFromAccess(access) : null;
        if (initial) {
          setUser(initial);
          setAuthUser(initial);
        }
        invalidateSessionCaches("soft");
      } catch (err) {
        // Only logout on definitive auth failure ΓÇö transient network/5xx should retry on next 401.
        if (err instanceof ApiError && err.status === 401) {
          logout();
        }
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const token = getAccessToken();
      if (!token || !getRefreshToken()) {
        return;
      }

      if (isTokenExpired(token)) {
        try {
          await refreshAccessTokenSingleFlight();
        } catch {
          clearAuthSession();
          return;
        }
      }

      const access = getAccessToken();
      const refresh = getRefreshToken();
      if (!access || !refresh) {
        return;
      }

      setAuthToken(access);
      const initialUser = bootstrapUserFromAccess(access);
      if (!cancelled && initialUser) {
        setAuthUser(initialUser);
        setUser(initialUser);
        // Paint protected routes immediately from JWT/stored profile; hydrate in background.
        setLoading(false);
      }

      try {
        const { user: me, memberships } = await hydrateUserAndMemberships({
          access,
          fetchMemberships: "if-empty",
          fallbackToTokenOnMeFailure: true,
        });
        if (cancelled) return;

        setUser(me);
        setAuthUser(me);
        persistAuthSuccess({
          access_token: access,
          refresh_token: refresh,
          user: me,
          memberships,
        });
      } catch {
        const fallback = userFromToken(access);
        if (!cancelled && fallback) {
          setUser(fallback);
          setAuthUser(fallback);
        }
      }
    }

    void restoreSession().finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return subscribeAuthSync((payload) => {
      if (!mountedRef.current) return;

      const currentTenantId = tenantIdFromToken(getAccessToken()) ?? user?.tenant_id ?? null;
      if (!shouldApplyAuthSync(currentTenantId, payload)) return;

      applySession(
        payload.access_token,
        payload.refresh_token,
        payload.user,
        payload.memberships,
        "soft"
      );
    });
  }, [applySession, user?.tenant_id]);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      verifyOtp,
      selectTenant,
      resendOtp,
      logout,
      switchTenant,
      // TODO: remove alias after callers migrate to switchTenant
      switchOrganisation: switchTenant,
      refreshUser,
      challengeToken,
      tenantPicker,
      tenantSelectToken,
    }),
    [
      user,
      loading,
      login,
      verifyOtp,
      selectTenant,
      resendOtp,
      logout,
      switchTenant,
      refreshUser,
      challengeToken,
      tenantPicker,
      tenantSelectToken,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
