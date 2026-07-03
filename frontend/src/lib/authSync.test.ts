import { describe, expect, it } from "vitest";

import type { AuthUser } from "@/api/types";
import { authSyncTenantId, shouldApplyAuthSync, type AuthSyncPayload } from "@/lib/authSync";

const tenantA = "11111111-1111-1111-1111-111111111111";
const tenantB = "22222222-2222-2222-2222-222222222222";

function payloadFor(tenantId: string): AuthSyncPayload {
  const user = {
    id: 1,
    email: "user@example.com",
    full_name: "User",
    role: "admin",
    tenant_id: tenantId,
    tenant_name: "Org",
    tenant_slug: "org",
    tenant_timezone: "Australia/Sydney",
    tenant_locale: "en-AU",
  } satisfies AuthUser;
  return {
    access_token: "access",
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

  it("allows sync when no current tenant is established yet", () => {
    expect(shouldApplyAuthSync(null, payloadFor(tenantA))).toBe(true);
  });

  it("extracts tenant id from payload", () => {
    expect(authSyncTenantId(payloadFor(tenantB))).toBe(tenantB);
  });
});
