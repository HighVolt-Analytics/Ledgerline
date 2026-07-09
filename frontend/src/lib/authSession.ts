import type { AuthUser } from "@/api/types";
import type { TenantAccountSummary } from "@/lib/authApi";

export const PROFILE_UPDATED_EVENT = "ledgerline:profile-updated";
const ACCESS_KEY = "ledgerline_access_token";
const REFRESH_KEY = "ledgerline_refresh_token";
const USER_KEY = "ledgerline_user";
const MEMBERSHIPS_KEY = "ledgerline_memberships";
const LAST_TENANT_KEY = "ledgerline_last_tenant_id";

function readWithMigration(key: string): string | null {
  if (typeof localStorage === "undefined") return null;
  const fromLocal = localStorage.getItem(key);
  if (fromLocal !== null) return fromLocal;
  if (typeof sessionStorage === "undefined") return null;
  const fromSession = sessionStorage.getItem(key);
  if (fromSession === null) return null;
  localStorage.setItem(key, fromSession);
  sessionStorage.removeItem(key);
  return fromSession;
}

function writeAuthItem(key: string, value: string) {
  localStorage.setItem(key, value);
  if (typeof sessionStorage !== "undefined") {
    sessionStorage.removeItem(key);
  }
}

function removeAuthItem(key: string) {
  localStorage.removeItem(key);
  if (typeof sessionStorage !== "undefined") {
    sessionStorage.removeItem(key);
  }
}

export function loadMembershipsFromSession(): TenantAccountSummary[] {
  return getStoredMemberships();
}

export function rememberLastTenant(tenantId: string) {
  localStorage.setItem(LAST_TENANT_KEY, String(tenantId));
}

export function getLastTenantId(): string | null {
  const raw = localStorage.getItem(LAST_TENANT_KEY)?.trim();
  return raw || null;
}

export function getAccessToken(): string | null {
  return readWithMigration(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return readWithMigration(REFRESH_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = readWithMigration(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function getStoredMemberships(): TenantAccountSummary[] {
  const raw = readWithMigration(MEMBERSHIPS_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as TenantAccountSummary[];
  } catch {
    return [];
  }
}

export function persistMemberships(memberships: TenantAccountSummary[]) {
  writeAuthItem(MEMBERSHIPS_KEY, JSON.stringify(memberships));
}

export function persistAuthSuccess(payload: {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
  memberships?: TenantAccountSummary[];
}) {
  writeAuthItem(ACCESS_KEY, payload.access_token);
  writeAuthItem(REFRESH_KEY, payload.refresh_token);
  writeAuthItem(USER_KEY, JSON.stringify(payload.user));
  if (payload.memberships !== undefined) {
    persistMemberships(payload.memberships);
  }
}

export function clearAuthSession() {
  removeAuthItem(ACCESS_KEY);
  removeAuthItem(REFRESH_KEY);
  removeAuthItem(USER_KEY);
  removeAuthItem(MEMBERSHIPS_KEY);
  localStorage.removeItem(LAST_TENANT_KEY);
}
