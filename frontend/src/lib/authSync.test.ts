import { describe, expect, it } from "vitest";

import type { AuthUser } from "@/api/types";
import { authSyncTenantId, shouldApplyAuthSync, type AuthSyncPayload } from "@/lib/authSync";

const tenantA = "11111111-1111-1111-1111-111111111111";
const tenantB = "22222222-2222-2222-2222-222222222222";

function jwtWithTenant(tenantId: string): string {
  const payload = btoa(JSON.stringify({ tenant_id: tenantId, sub: "1" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `hdr.${payload}.sig`;
}

function payloadFor(tenantId: string, profileTenantId = tenantId): AuthSyncPayload {
  const user = {
    id: 1,
    email: "user@example.com",
    full_name: "User",
    role: "admin",
    tenant_id: profileTenantId,
    tenant_name: "Org",
    tenant_slug: "org",
    tenant_timezone: "Australia/Sydney",
    tenant_locale: "en-AU",
  } satisfies AuthUser;
  return {
    access_token: jwtWithTenant(tenantId),
    refresh_token: "refresh",
    user,
  };
}

describe("shouldApplyAuthSync", () => {
  it("allows sync when current tenant matches incoming", () => {
    expect(shouldApplyAuthSync(tenantA, payloadFor(tenantA))).toBe(true);
  });

  it("blocks cross-tenant sync from another tab", () => {
    expect(shouldApplyAuthSync(tenantA, payloadFor(tenantB))).toBe(false);
  });

  it("does not mutate current tab when different-tenant payload arrives", () => {
    const current = tenantA;
    const incoming = payloadFor(tenantB);
    expect(shouldApplyAuthSync(current, incoming)).toBe(false);
    // Caller must not apply session / clear caches for mismatched tenants.
    expect(authSyncTenantId(incoming)).toBe(tenantB);
    expect(authSyncTenantId(incoming)).not.toBe(current);
  });

  it("rejects payload when JWT tenant and profile tenant disagree", () => {
    expect(shouldApplyAuthSync(tenantA, payloadFor(tenantA, tenantB))).toBe(false);
  });

  it("allows sync when no current tenant is established yet", () => {
    expect(shouldApplyAuthSync(null, payloadFor(tenantA))).toBe(true);
  });

  it("extracts tenant id from access token", () => {
    expect(authSyncTenantId(payloadFor(tenantB))).toBe(tenantB);
  });
});
