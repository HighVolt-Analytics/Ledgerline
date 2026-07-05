import { describe, expect, it } from "vitest";

import type { AuthUser } from "@/api/types";
import { mergeStoredUserWithToken, userFromToken } from "@/lib/authToken";

const tenantA = "11111111-1111-1111-1111-111111111111";
const tenantB = "22222222-2222-2222-2222-222222222222";

function jwtWithTenant(tenantId: string): string {
  const payload = btoa(JSON.stringify({ tenant_id: tenantId, sub: "42", email: "user@example.com" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `hdr.${payload}.sig`;
}

function storedUserForTenant(tenantId: string): AuthUser {
  return {
    id: 42,
    email: "user@example.com",
    full_name: "Stored User",
    role: "admin",
    tenant_id: tenantId,
    tenant_name: tenantId === tenantA ? "Org A" : "Org B",
    tenant_slug: tenantId === tenantA ? "org-a" : "org-b",
    tenant_timezone: "Australia/Sydney",
    tenant_locale: "en-AU",
    onboarding_completed: true,
  };
}

describe("mergeStoredUserWithToken", () => {
  it("drops stale org-specific fields when tenant changes", () => {
    const stored = storedUserForTenant(tenantA);
    const tokenProfile = userFromToken(jwtWithTenant(tenantB))!;
    const merged = mergeStoredUserWithToken(stored, tokenProfile);

    expect(merged.tenant_id).toBe(tenantB);
    expect(merged.tenant_name).toBe("");
    expect(merged.tenant_timezone).toBe("Australia/Sydney");
    expect(merged.onboarding_completed).toBeUndefined();
  });

  it("keeps stored display fields when tenant is unchanged", () => {
    const stored = storedUserForTenant(tenantA);
    const tokenProfile = userFromToken(jwtWithTenant(tenantA))!;
    const merged = mergeStoredUserWithToken(stored, tokenProfile);

    expect(merged.tenant_id).toBe(tenantA);
    expect(merged.tenant_name).toBe("Org A");
    expect(merged.onboarding_completed).toBe(true);
  });
});
