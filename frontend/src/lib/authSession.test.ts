import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  persistAuthSuccess,
} from "@/lib/authSession";
import type { AuthUser } from "@/api/types";

const ACCESS_KEY = "ledgerline_access_token";
const REFRESH_KEY = "ledgerline_refresh_token";

function mockStorage() {
  const local = new Map<string, string>();
  const session = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => local.get(key) ?? null,
    setItem: (key: string, value: string) => {
      local.set(key, value);
    },
    removeItem: (key: string) => {
      local.delete(key);
    },
    clear: () => local.clear(),
  });
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => session.get(key) ?? null,
    setItem: (key: string, value: string) => {
      session.set(key, value);
    },
    removeItem: (key: string) => {
      session.delete(key);
    },
    clear: () => session.clear(),
  });
  return { local, session };
}

const user: AuthUser = {
  id: 1,
  email: "user@example.com",
  full_name: "User",
  role: "member",
  tenant_id: "11111111-1111-1111-1111-111111111111",
  tenant_name: "Acme",
  tenant_slug: "acme",
  tenant_timezone: "Asia/Singapore",
  tenant_locale: "en-SG",
};

beforeEach(() => {
  mockStorage();
});

afterEach(() => {
  clearAuthSession();
  vi.unstubAllGlobals();
});

describe("authSession localStorage", () => {
  it("persists tokens in localStorage", () => {
    persistAuthSuccess({
      access_token: "access-1",
      refresh_token: "refresh-1",
      user,
    });
    expect(localStorage.getItem(ACCESS_KEY)).toBe("access-1");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-1");
    expect(getAccessToken()).toBe("access-1");
    expect(getRefreshToken()).toBe("refresh-1");
  });

  it("migrates legacy sessionStorage tokens to localStorage", () => {
    sessionStorage.setItem(ACCESS_KEY, "legacy-access");
    sessionStorage.setItem(REFRESH_KEY, "legacy-refresh");

    expect(getAccessToken()).toBe("legacy-access");
    expect(getRefreshToken()).toBe("legacy-refresh");
    expect(localStorage.getItem(ACCESS_KEY)).toBe("legacy-access");
    expect(sessionStorage.getItem(ACCESS_KEY)).toBeNull();
  });
});
