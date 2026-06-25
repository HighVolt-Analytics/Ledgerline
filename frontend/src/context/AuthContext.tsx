import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api, setAuthToken, setAuthUser, setUnauthorizedHandler } from "@/api/client";
import type { AuthUser } from "@/api/types";
import {
  apiLogin,
  apiResendOtp,
  apiSelectTenant,
  apiVerifyOtp,
  fetchMyMemberships,
  type TenantAccountSummary,
} from "@/lib/authApi";
import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  getStoredMemberships,
  getStoredUser,
  persistAuthSuccess,
  rememberLastTenant,
} from "@/lib/authSession";
import { isTokenExpired, userFromToken } from "@/lib/authToken";
import { refreshAccessTokenSingleFlight } from "@/lib/authTokenRefresh";
import { homePathForRole } from "@/lib/roles";
import { withRouterBasename } from "@/lib/routerBasename";
import { queryClient } from "@/lib/queryClient";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<"otp">;
  verifyOtp: (otp: string) => Promise<"done" | "pick-tenant">;
  selectTenant: (tenantId: string) => Promise<void>;
  resendOtp: () => Promise<void>;
  logout: () => void;
  switchTenant: (tenantId: string) => Promise<void>;
  switchOrganisation: (tenantId: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  challengeToken: string | null;
  tenantPicker: TenantAccountSummary[];
  tenantSelectToken: string | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [tenantSelectToken, setTenantSelectToken] = useState<string | null>(null);
  const [tenantPicker, setTenantPicker] = useState<TenantAccountSummary[]>([]);

  const applySession = useCallback(
    (
      access: string,
      refresh: string,
      profile: AuthUser,
      memberships?: TenantAccountSummary[]
    ) => {
      persistAuthSuccess({
        access_token: access,
        refresh_token: refresh,
        user: profile,
        memberships,
      });
      setAuthToken(access);
      setAuthUser(profile);
      setUser(profile);
    },
    []
  );

  const logout = useCallback(() => {
    const refresh = getRefreshToken();
    queryClient.clear();
    clearAuthSession();
    setAuthToken(null);
    setAuthUser(null);
    setUser(null);
    setChallengeToken(null);
    setTenantSelectToken(null);
    setTenantPicker([]);
    void api.logout(refresh ?? undefined).catch(() => undefined);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await apiLogin(email, password);
    setChallengeToken(data.challenge_token);
    return "otp" as const;
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
          sessionStorage.setItem("ledgerline_memberships", JSON.stringify(data.accounts));
        }
        return "pick-tenant" as const;
      }
      if (!data.access_token || !data.refresh_token || !data.user) {
        throw new Error("Invalid login response");
      }
      applySession(data.access_token, data.refresh_token, data.user);
      queryClient.clear();
      return "done" as const;
    },
    [applySession, challengeToken]
  );

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
      queryClient.clear();
    },
    [applySession, tenantSelectToken]
  );

  const resendOtp = useCallback(async () => {
    if (!challengeToken) throw new Error("Login session expired");
    const data = await apiResendOtp(challengeToken);
    setChallengeToken(data.challenge_token);
  }, [challengeToken]);

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
      queryClient.clear();
      window.location.assign(withRouterBasename(homePathForRole(data.user.role)));
    },
    [applySession]
  );

  const refreshUser = useCallback(async () => {
    const me = await api.me();
    setUser(me);
    setAuthUser(me);
    const refresh = getRefreshToken();
    const access = getAccessToken();
    if (access && refresh) {
      persistAuthSuccess({ access_token: access, refresh_token: refresh, user: me });
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      if (!getRefreshToken()) {
        logout();
        return;
      }
      try {
        await refreshAccessTokenSingleFlight();
        const access = getAccessToken();
        const stored = getStoredUser();
        const tokenProfile = access ? userFromToken(access) : null;
        const initial =
          tokenProfile && stored
            ? { ...stored, ...tokenProfile, tenant_id: tokenProfile.tenant_id }
            : tokenProfile ?? stored;
        if (initial) {
          setUser(initial);
          setAuthUser(initial);
        }
      } catch (err) {
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
      const refresh = getRefreshToken();
      if (!token || !refresh) {
        setLoading(false);
        return;
      }

      if (isTokenExpired(token)) {
        try {
          await refreshAccessTokenSingleFlight();
        } catch {
          clearAuthSession();
          setLoading(false);
          return;
        }
      }

      const access = getAccessToken();
      if (!access) {
        setLoading(false);
        return;
      }

      setAuthToken(access);
      const tokenProfile = userFromToken(access);
      const storedUser = getStoredUser();
      const initialUser =
        tokenProfile && storedUser
          ? { ...storedUser, ...tokenProfile, tenant_id: tokenProfile.tenant_id }
          : tokenProfile ?? storedUser;
      if (initialUser) {
        setAuthUser(initialUser);
        setUser(initialUser);
      }

      try {
        const me = await api.me();
        if (!cancelled) {
          setUser(me);
          setAuthUser(me);
        }
        if (!cancelled && getStoredMemberships().length === 0) {
          const memberships = await fetchMyMemberships(access);
          if (memberships.length) {
            sessionStorage.setItem("ledgerline_memberships", JSON.stringify(memberships));
          }
        }
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
