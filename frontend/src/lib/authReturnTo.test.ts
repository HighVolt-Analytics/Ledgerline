import { describe, expect, it } from "vitest";

import {
  buildLoginPathWithReturn,
  postLoginPathForRole,
  readReturnTo,
  sanitizeReturnPath,
} from "@/lib/authReturnTo";

describe("sanitizeReturnPath", () => {
  it("allows vault deep links", () => {
    expect(sanitizeReturnPath("/vault?invoice=36")).toBe("/vault?invoice=36");
  });

  it("blocks open redirects and login loops", () => {
    expect(sanitizeReturnPath("//evil.com/vault")).toBeNull();
    expect(sanitizeReturnPath("https://evil.com")).toBeNull();
    expect(sanitizeReturnPath("/login")).toBeNull();
    expect(sanitizeReturnPath("/login?returnTo=%2F")).toBeNull();
  });
});

describe("readReturnTo", () => {
  it("parses returnTo query param", () => {
    const params = new URLSearchParams("returnTo=%2Fvault%3Finvoice%3D9");
    expect(readReturnTo(params)).toBe("/vault?invoice=9");
  });
});

describe("buildLoginPathWithReturn", () => {
  it("encodes safe return path", () => {
    expect(buildLoginPathWithReturn("/vault?invoice=1")).toBe(
      "/login?returnTo=%2Fvault%3Finvoice%3D1"
    );
  });

  it("falls back to plain login for unsafe paths", () => {
    expect(buildLoginPathWithReturn("//evil")).toBe("/login");
  });
});

describe("postLoginPathForRole", () => {
  it("prefers returnTo over role home", () => {
    expect(postLoginPathForRole("member", "/vault?invoice=3")).toBe("/vault?invoice=3");
  });

  it("uses dashboard for members without returnTo", () => {
    expect(postLoginPathForRole("member", null)).toBe("/");
  });
});
