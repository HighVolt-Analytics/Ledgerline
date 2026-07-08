import { describe, expect, it } from "vitest";

import { apiPathWithoutQuery, isTenantScopedApiPath } from "@/api/client";

describe("invite API path tenant exemption", () => {
  it("strips query strings before matching", () => {
    expect(apiPathWithoutQuery("/api/auth/invite/preview?token=abc")).toBe(
      "/api/auth/invite/preview"
    );
  });

  it("does not require tenant scope for tenant invite preview with token", () => {
    expect(isTenantScopedApiPath("/api/auth/invite/preview?token=abc")).toBe(false);
  });

  it("does not require tenant scope for tenant invite accept", () => {
    expect(isTenantScopedApiPath("/api/auth/invite/accept")).toBe(false);
  });

  it("does not require tenant scope for mailbox invite preview with token", () => {
    expect(isTenantScopedApiPath("/api/mailboxes/invites/preview?token=abc")).toBe(false);
  });

  it("does not require tenant scope for mailbox invite authorize", () => {
    expect(isTenantScopedApiPath("/api/mailboxes/invites/authorize?token=abc")).toBe(false);
  });

  it("does not require tenant scope for public billing signup checkout", () => {
    expect(isTenantScopedApiPath("/api/billing/signup/checkout")).toBe(false);
    expect(isTenantScopedApiPath("/api/billing/signup/status/cs_test_123")).toBe(false);
  });

  it("does not require tenant scope for public billing plans catalogue", () => {
    expect(isTenantScopedApiPath("/api/billing/plans?country=AU")).toBe(false);
  });

  it("still requires tenant scope for normal API paths", () => {
    expect(isTenantScopedApiPath("/api/invoices")).toBe(true);
    expect(isTenantScopedApiPath("/api/tenants/current/members/invite")).toBe(true);
  });
});
