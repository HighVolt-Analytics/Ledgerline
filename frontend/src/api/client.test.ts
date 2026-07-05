import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  clearGetCache,
  setAuthToken,
} from "@/api/client";

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
  setAuthToken(jwtWithTenant(tenantA));
  clearGetCache();
});

afterEach(() => {
  setAuthToken(null);
  clearGetCache();
  vi.unstubAllGlobals();
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
