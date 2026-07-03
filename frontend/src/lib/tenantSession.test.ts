import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAuthToken } from "@/api/client";
import {
  guardedTenantData,
  isTenantScopeConsistent,
  tenantSessionWillChange,
} from "@/lib/tenantSession";

const tenantA = "11111111-1111-1111-1111-111111111111";
const tenantB = "22222222-2222-2222-2222-222222222222";

const storage = new Map<string, string>();

function jwtWithTenant(tenantId: string): string {
  const payload = btoa(JSON.stringify({ tenant_id: tenantId, sub: "1" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `hdr.${payload}.sig`;
}

beforeEach(() => {
  storage.clear();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
    removeItem: (key: string) => {
      storage.delete(key);
    },
    clear: () => {
      storage.clear();
    },
  });
  setAuthToken(null);
});

afterEach(() => {
  setAuthToken(null);
  storage.clear();
  vi.unstubAllGlobals();
});

describe("tenantSessionWillChange", () => {
  it("detects tenant change before persisting the next access token", () => {
    sessionStorage.setItem("ledgerline_access_token", jwtWithTenant(tenantA));
    expect(tenantSessionWillChange(jwtWithTenant(tenantB))).toBe(true);
  });

  it("returns false when tenant is unchanged", () => {
    sessionStorage.setItem("ledgerline_access_token", jwtWithTenant(tenantA));
    expect(tenantSessionWillChange(jwtWithTenant(tenantA))).toBe(false);
  });
});

describe("guardedTenantData", () => {
  const tenantAInvoices = [{ id: 1, vendor: "Tenant A vendor" }];
  const tenantBInvoices = [{ id: 2, vendor: "Tenant B vendor" }];

  it("hides tenant A rows when active profile tenant is B", () => {
    setAuthToken(jwtWithTenant(tenantB));
    expect(
      guardedTenantData(tenantAInvoices, {
        profileTenantId: tenantB,
        dataTenantId: tenantA,
      })
    ).toBeUndefined();
  });

  it("shows tenant B rows when profile and data tenant match", () => {
    setAuthToken(jwtWithTenant(tenantB));
    expect(
      guardedTenantData(tenantBInvoices, {
        profileTenantId: tenantB,
        dataTenantId: tenantB,
      })
    ).toEqual(tenantBInvoices);
  });

  it("hides data while loading after tenant switch", () => {
    setAuthToken(jwtWithTenant(tenantB));
    expect(
      guardedTenantData(tenantBInvoices, {
        profileTenantId: tenantB,
        isLoading: true,
        dataTenantId: tenantB,
      })
    ).toBeUndefined();
  });

  it("never surfaces tenant A invoice ids after switching to tenant B", () => {
    setAuthToken(jwtWithTenant(tenantB));
    const visible = guardedTenantData(tenantAInvoices, {
      profileTenantId: tenantB,
      dataTenantId: tenantA,
    });
    expect(visible).toBeUndefined();
    expect(tenantAInvoices.map((row) => row.id)).toEqual([1]);
  });
});

describe("isTenantScopeConsistent", () => {
  it("is false when profile tenant is set but jwt tenant is absent", () => {
    expect(isTenantScopeConsistent(tenantA)).toBe(false);
  });

  it("is true when profile and jwt tenant match", () => {
    setAuthToken(jwtWithTenant(tenantB));
    expect(isTenantScopeConsistent(tenantB)).toBe(true);
  });
});
