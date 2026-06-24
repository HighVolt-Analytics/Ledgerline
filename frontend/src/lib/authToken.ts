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
