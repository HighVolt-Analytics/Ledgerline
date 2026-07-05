import type { AuthUser } from "@/api/types";
import {
  DEFAULT_TENANT_LOCALE,
  DEFAULT_TENANT_TIMEZONE,
} from "@/lib/tenantTime";

type JwtPayload = {
  sub?: string;
  tenant_id?: string;
  org_id?: string;
  tenant_slug?: string;
  email?: string;
  role?: string;
  exp?: number;
  type?: string;
  is_support_session?: boolean;
};

export function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const segment = token.split(".")[1];
    if (!segment) return null;
    const json = atob(segment.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

export function getTokenExpiryMs(token: string): number | null {
  const payload = decodeJwtPayload(token);
  if (!payload?.exp) return null;
  return payload.exp * 1000;
}

export function isTokenExpired(token: string, skewMs = 30_000): boolean {
  const expiry = getTokenExpiryMs(token);
  if (!expiry) return true;
  return Date.now() >= expiry - skewMs;
}

/** Fallback profile when /me is temporarily unreachable but the JWT is still valid. */
export function tenantIdFromToken(token: string | null | undefined): string | null {
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  const tenantId = payload?.tenant_id ?? payload?.org_id;
  return tenantId ? String(tenantId) : null;
}

export function userFromToken(token: string): AuthUser | null {
  const payload = decodeJwtPayload(token);
  const tenantId = tenantIdFromToken(token);
  if (!payload?.sub || !tenantId) return null;
  const email = String(payload.email ?? "");
  return {
    id: Number(payload.sub),
    email,
    full_name: email ? email.split("@")[0] : "User",
    role: String(payload.role ?? "member"),
    tenant_id: tenantId,
    tenant_name: "",
    tenant_slug: String(payload.tenant_slug ?? ""),
    tenant_timezone: DEFAULT_TENANT_TIMEZONE,
    tenant_locale: DEFAULT_TENANT_LOCALE,
    is_support_session: Boolean(payload.is_support_session),
    onboarding_completed: undefined,
  };
}

/** JWT omits display fields — keep persisted profile values when merging. */
export function mergeStoredUserWithToken(stored: AuthUser, tokenProfile: AuthUser): AuthUser {
  const tenantChanged = stored.tenant_id !== tokenProfile.tenant_id;
  if (tenantChanged) {
    return {
      ...tokenProfile,
      full_name: tokenProfile.full_name || stored.full_name,
      email: tokenProfile.email || stored.email,
      role: tokenProfile.role || stored.role,
    };
  }
  return {
    ...stored,
    ...tokenProfile,
    tenant_id: tokenProfile.tenant_id,
    tenant_name: stored.tenant_name || tokenProfile.tenant_name,
    tenant_slug: stored.tenant_slug || tokenProfile.tenant_slug,
    full_name: tokenProfile.full_name || stored.full_name,
    email: tokenProfile.email || stored.email,
    role: tokenProfile.role || stored.role,
    onboarding_completed:
      tokenProfile.onboarding_completed ?? stored.onboarding_completed,
  };
}
