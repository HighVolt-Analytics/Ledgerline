import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api, setAuthToken, setUnauthorizedHandler } from "@/api/client";
import type { AuthUser } from "@/api/types";
import { isTokenExpired, userFromToken } from "@/lib/authToken";

const TOKEN_KEY = "ledgerline_token";
const SESSION_REFRESH_MS = 30 * 60 * 1000;

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    org_name: string;
    org_slug: string;
    email: string;
    password: string;
    full_name: string;
  }) => Promise<void>;
  logout: () => void;
  switchOrganisation: (orgId: number) => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const applyToken = useCallback((token: string | null) => {
    setAuthToken(token);
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }, []);

  const logout = useCallback(() => {
    applyToken(null);
    setUser(null);
    localStorage.removeItem("ledgerline_active_org_id");
    void api.logout().catch(() => undefined);
  }, [applyToken]);

  const refreshSession = useCallback(async () => {
    const data = await api.refreshSession();
    applyToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, [applyToken]);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await api.login(email, password);
      applyToken(data.access_token);
      setUser(data.user);
    },
    [applyToken]
  );

  const switchOrganisation = useCallback(
    async (orgId: number) => {
      const data = await api.switchOrganisation(orgId);
      applyToken(data.access_token);
      setUser(data.user);
    },
    [applyToken]
  );

  const refreshUser = useCallback(async () => {
    const me = await api.me();
    setUser(me);
  }, []);

  const register = useCallback(
    async (payload: {
      org_name: string;
      org_slug: string;
      email: string;
      password: string;
      full_name: string;
    }) => {
      const data = await api.register(payload);
      applyToken(data.access_token);
      setUser(data.user);
    },
    [applyToken]
  );

  useEffect(() => {
    setUnauthorizedHandler(async () => {
      if (!localStorage.getItem(TOKEN_KEY)) {
        logout();
        return;
      }
      try {
        await refreshSession();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          logout();
        }
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [logout, refreshSession]);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) {
        setLoading(false);
        return;
      }

      if (isTokenExpired(token)) {
        applyToken(null);
        setLoading(false);
        return;
      }

      applyToken(token);

      for (let attempt = 0; attempt < 3; attempt++) {
        if (cancelled) return;
        try {
          const me = await api.me();
          if (!cancelled) setUser(me);
          return;
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            try {
              await refreshSession();
            } catch {
              applyToken(null);
              if (!cancelled) setUser(null);
            }
            return;
          }
          if (attempt < 2) {
            await sleep(750 * (attempt + 1));
          }
        }
      }

      if (!cancelled) {
        const fallback = userFromToken(token);
        if (fallback) setUser(fallback);
      }
    }

    void restoreSession().finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [applyToken, refreshSession]);

  useEffect(() => {
    if (!user) return;

    const maybeRefresh = () => {
      if (document.visibilityState !== "visible") return;
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token || isTokenExpired(token)) {
        logout();
        return;
      }
      void refreshSession().catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          logout();
        }
      });
    };

    const id = window.setInterval(maybeRefresh, SESSION_REFRESH_MS);
    window.addEventListener("focus", maybeRefresh);
    document.addEventListener("visibilitychange", maybeRefresh);

    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", maybeRefresh);
      document.removeEventListener("visibilitychange", maybeRefresh);
    };
  }, [user, logout, refreshSession]);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, switchOrganisation, refreshUser }),
    [user, loading, login, register, logout, switchOrganisation, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
