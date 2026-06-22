import type { AuthUser } from "@/api/types";

type JwtPayload = {
  sub?: string;
  tenant_id?: string;
  org_id?: string;
  tenant_slug?: string;
  email?: string;
  role?: string;
  exp?: number;
  type?: string;
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
export function userFromToken(token: string): AuthUser | null {
  const payload = decodeJwtPayload(token);
  const tenantId = payload?.tenant_id ?? payload?.org_id;
  if (!payload?.sub || !tenantId) return null;
  const email = String(payload.email ?? "");
  return {
    id: Number(payload.sub),
    email,
    full_name: email ? email.split("@")[0] : "User",
    role: String(payload.role ?? "member"),
    tenant_id: String(tenantId),
    tenant_name: "",
    tenant_slug: String(payload.tenant_slug ?? ""),
  };
}
