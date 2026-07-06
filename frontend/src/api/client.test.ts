import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  clearGetCache,
  hydrateAuthTokenFromSession,
  setAuthToken,
} from "@/api/client";

const ACCESS_KEY = "ledgerline_access_token";

function mockSessionStorage() {
  const store = new Map<string, string>();
  const sessionStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
  };
  vi.stubGlobal("sessionStorage", sessionStorage);
  return sessionStorage;
}

const tenantA = "11111111-1111-1111-1111-111111111111";
const tenantB = "22222222-2222-2222-2222-222222222222";

function jwtWithTenant(tenantId: string): string {
  const payload = btoa(JSON.stringify({ tenant_id: tenantId, sub: "1" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `hdr.${payload}.sig`;
}

function envelope<T>(data: T) {
  return new Response(JSON.stringify({ data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockSessionStorage();
  setAuthToken(jwtWithTenant(tenantA));
  clearGetCache();
});

afterEach(() => {
  setAuthToken(null);
  clearGetCache();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("tenant-scoped request guards", () => {
  it("rejects tenant API calls when tenant id cannot be resolved", async () => {
    setAuthToken(null);
    sessionStorage.clear();

    await expect(api.listMailboxes()).rejects.toMatchObject({
      message: "Tenant scope required",
      status: 401,
    });
  });

  it("sends Authorization from sessionStorage when in-memory token is unset", async () => {
    setAuthToken(null);
    sessionStorage.setItem(ACCESS_KEY, jwtWithTenant(tenantA));

    let authHeader: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        authHeader = headers.get("Authorization");
        return Promise.resolve(envelope([]));
      })
    );

    await api.listMailboxes();
    expect(authHeader).toMatch(/^Bearer /);
  });
});

describe("GET tenant scope validation", () => {
  it("completes when cache generation bumps mid-flight for same tenant", async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(() => fetchPromise)
    );

    const pending = api.getRuleBookConfig();
    clearGetCache();
    resolveFetch(envelope({ document_sets: [] }));

    await expect(pending).resolves.toEqual({ document_sets: [] });
  });

  it("rejects when active tenant id changes before GET completes", async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(() => fetchPromise)
    );

    const pending = api.getRuleBookConfig();
    setAuthToken(jwtWithTenant(tenantB));
    resolveFetch(envelope({ document_sets: [] }));

    await expect(pending).rejects.toMatchObject({
      message: "Tenant scope changed",
      status: 409,
    });
  });
});
