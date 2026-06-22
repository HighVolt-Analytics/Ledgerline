import type { AuthUser } from "@/api/types";
import type { TenantAccountSummary } from "@/lib/authApi";

const ACCESS_KEY = "ledgerline_access_token";
const REFRESH_KEY = "ledgerline_refresh_token";
const USER_KEY = "ledgerline_user";
const MEMBERSHIPS_KEY = "ledgerline_memberships";

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function getStoredMemberships(): TenantAccountSummary[] {
  const raw = sessionStorage.getItem(MEMBERSHIPS_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as TenantAccountSummary[];
  } catch {
    return [];
  }
}

export function persistAuthSuccess(payload: {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
  memberships?: TenantAccountSummary[];
}) {
  sessionStorage.setItem(ACCESS_KEY, payload.access_token);
  sessionStorage.setItem(REFRESH_KEY, payload.refresh_token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(payload.user));
  if (payload.memberships) {
    sessionStorage.setItem(MEMBERSHIPS_KEY, JSON.stringify(payload.memberships));
  }
}

export function clearAuthSession() {
  sessionStorage.removeItem(ACCESS_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
  sessionStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(MEMBERSHIPS_KEY);
}
