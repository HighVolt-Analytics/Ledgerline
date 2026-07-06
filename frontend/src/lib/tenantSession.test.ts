import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAuthToken, setAuthToken, setAuthUser, clearGetCache } from "@/api/client";
import {
  beginTenantTransition,
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  clearAllTenantCaches,
  endTenantTransition,
  getTenantDataGeneration,
  guardedTenantData,
  isTenantFetchAbortError,
  isTenantFetchScopeCurrent,
  isTenantScopeConsistent,
  isTenantTransitionActive,
  TenantFetchAbortError,
  TENANT_SCOPE_CHANGED_MESSAGE,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  tenantSessionWillChange,
} from "@/lib/tenantSession";
import { ApiError } from "@/api/client";

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
  setAuthUser(null);
  endTenantTransition();
});

afterEach(() => {
  setAuthToken(null);
  setAuthUser(null);
  endTenantTransition();
  storage.clear();
  vi.unstubAllGlobals();
});

describe("tenantSessionWillChange", () => {
  it("reads previous tenant from in-memory token before persist", () => {
    setAuthToken(jwtWithTenant(tenantA));
    sessionStorage.setItem("ledgerline_access_token", jwtWithTenant(tenantA));
    expect(tenantSessionWillChange(jwtWithTenant(tenantB), getAuthToken())).toBe(true);
  });

  it("detects tenant change even if sessionStorage already has the next token", () => {
    setAuthToken(jwtWithTenant(tenantA));
    // Simulate a buggy caller that wrote sessionStorage first.
    sessionStorage.setItem("ledgerline_access_token", jwtWithTenant(tenantB));
    expect(tenantSessionWillChange(jwtWithTenant(tenantB), getAuthToken())).toBe(true);
  });

  it("returns false when tenant is unchanged", () => {
    setAuthToken(jwtWithTenant(tenantA));
    expect(tenantSessionWillChange(jwtWithTenant(tenantA), getAuthToken())).toBe(false);
  });
});

describe("clearAllTenantCaches", () => {
  it("bumps generation and enters transition on tenant change", () => {
    setAuthToken(jwtWithTenant(tenantA));
    const before = getTenantDataGeneration();
    clearAllTenantCaches();
    expect(getTenantDataGeneration()).toBe(before + 1);
    expect(isTenantTransitionActive()).toBe(true);
    expect(canRenderTenantOwnedUi(tenantA)).toBe(false);
  });

  it("does not leave transition active after same-tenant endTenantTransition", () => {
    setAuthToken(jwtWithTenant(tenantA));
    setAuthUser({
      id: 1,
      email: "a@example.com",
      full_name: "A",
      role: "admin",
      tenant_id: tenantA,
      tenant_name: "A",
      tenant_slug: "a",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    clearAllTenantCaches();
    endTenantTransition();
    expect(isTenantTransitionActive()).toBe(false);
    expect(isTenantScopeConsistent(tenantA)).toBe(true);
  });
});

describe("guardedTenantData", () => {
  const tenantAInvoices = [{ id: 1, vendor: "Tenant A vendor" }];
  const tenantBInvoices = [{ id: 2, vendor: "Tenant B vendor" }];

  it("hides tenant A rows when active profile tenant is B", () => {
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    expect(
      guardedTenantData(tenantAInvoices, {
        profileTenantId: tenantB,
        dataTenantId: tenantA,
        queryKeyTenantId: tenantA,
      })
    ).toBeUndefined();
  });

  it("shows tenant B rows when profile, jwt, and data tenant match", () => {
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    expect(
      guardedTenantData(tenantBInvoices, {
        profileTenantId: tenantB,
        dataTenantId: tenantB,
        queryKeyTenantId: tenantB,
      })
    ).toEqual(tenantBInvoices);
  });

  it("hides data while loading after tenant switch", () => {
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    expect(
      guardedTenantData(tenantBInvoices, {
        profileTenantId: tenantB,
        isLoading: true,
        dataTenantId: tenantB,
      })
    ).toBeUndefined();
  });

  it("hides data during transition even when tenants match", () => {
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    beginTenantTransition();
    expect(
      guardedTenantData(tenantBInvoices, {
        profileTenantId: tenantB,
        dataTenantId: tenantB,
      })
    ).toBeUndefined();
  });

  it("never surfaces tenant A invoice ids after switching to tenant B", () => {
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });
    const visible = guardedTenantData(tenantAInvoices, {
      profileTenantId: tenantB,
      dataTenantId: tenantA,
    });
    expect(visible).toBeUndefined();
  });
});

describe("tenant navigation regression", () => {
  it("discards in-flight tenant A scope after switch to B", () => {
    setAuthToken(jwtWithTenant(tenantA));
    const scopeA = captureTenantFetchScope();
    expect(isTenantFetchScopeCurrent(scopeA)).toBe(true);

    clearAllTenantCaches();
    setAuthToken(jwtWithTenant(tenantB));
    setAuthUser({
      id: 1,
      email: "b@example.com",
      full_name: "B",
      role: "admin",
      tenant_id: tenantB,
      tenant_name: "B",
      tenant_slug: "b",
      tenant_timezone: "UTC",
      tenant_locale: "en",
    });

    expect(isTenantFetchScopeCurrent(scopeA)).toBe(false);

    endTenantTransition();
    const pages = ["dashboard", "upload", "approvals", "vault", "vendors", "integrations", "search"];
    for (const page of pages) {
      const visible = guardedTenantData([{ id: 1, page, vendor: "Tenant A vendor" }], {
        profileTenantId: tenantB,
        dataTenantId: tenantA,
        queryKeyTenantId: tenantA,
      });
      expect(visible, page).toBeUndefined();
    }
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

  it("is false when jwt and profile disagree", () => {
    setAuthToken(jwtWithTenant(tenantA));
    expect(isTenantScopeConsistent(tenantB)).toBe(false);
  });
});

describe("isTenantFetchAbortError", () => {
  it("matches TenantFetchAbortError", () => {
    expect(isTenantFetchAbortError(new TenantFetchAbortError())).toBe(true);
  });

  it("matches ApiError 409 tenant scope changed", () => {
    expect(isTenantFetchAbortError(new ApiError(TENANT_SCOPE_CHANGED_MESSAGE, 409))).toBe(true);
  });

  it("does not match other ApiError statuses", () => {
    expect(isTenantFetchAbortError(new ApiError(TENANT_SCOPE_CHANGED_MESSAGE, 500))).toBe(false);
  });

  it("matches generic Error with tenant scope message", () => {
    expect(isTenantFetchAbortError(new Error(TENANT_SCOPE_CHANGED_MESSAGE))).toBe(true);
  });
});

describe("formatTenantLoadError", () => {
  it("does not append api hint for tenant scope changed", () => {
    expect(formatTenantLoadError(TENANT_SCOPE_CHANGED_MESSAGE, " port hint")).toBe(
      TENANT_SCOPE_CHANGED_MESSAGE
    );
  });

  it("appends api hint for other errors", () => {
    expect(formatTenantLoadError("Network error", " port hint")).toBe("Network error port hint");
  });
});

describe("handleTenantScopedLoadFailure", () => {
  it("invokes retry for scope abort errors", () => {
    const retry = vi.fn();
    expect(handleTenantScopedLoadFailure(new TenantFetchAbortError(), { retry })).toBe(true);
    expect(retry).toHaveBeenCalledOnce();
  });

  it("returns false for unrelated errors", () => {
    const retry = vi.fn();
    expect(handleTenantScopedLoadFailure(new Error("network"), { retry })).toBe(false);
    expect(retry).not.toHaveBeenCalled();
  });
});

describe("same-tenant cache bump vs tenant switch", () => {
  it("scope stays current after same-tenant GET cache clear only", () => {
    setAuthToken(jwtWithTenant(tenantA));
    const scope = captureTenantFetchScope();
    clearGetCache();
    expect(isTenantFetchScopeCurrent(scope)).toBe(true);
  });

  it("scope is stale after full tenant cache clear", () => {
    setAuthToken(jwtWithTenant(tenantA));
    const scope = captureTenantFetchScope();
    clearAllTenantCaches();
    expect(isTenantFetchScopeCurrent(scope)).toBe(false);
  });

  it("scope is stale after tenant id change", () => {
    setAuthToken(jwtWithTenant(tenantA));
    const scope = captureTenantFetchScope();
    clearAllTenantCaches();
    setAuthToken(jwtWithTenant(tenantB));
    expect(isTenantFetchScopeCurrent(scope)).toBe(false);
  });
});
