import { describe, expect, it } from "vitest";
import {
  ACCEPT_INVITE_PATH,
  ALL_PUBLIC_SIGNUP_PATHS,
  PUBLIC_SIGNUP_ALIASES,
  PUBLIC_SIGNUP_PATH,
  buildPublicSignupPath,
  buildPublicSignupUrl,
} from "@/lib/publicSignupRoutes";

describe("public signup routes", () => {
  it("uses /signup for token-less public self-serve signup", () => {
    expect(PUBLIC_SIGNUP_PATH).toBe("/signup");
  });

  it("exposes marketing-friendly alias paths", () => {
    expect(PUBLIC_SIGNUP_ALIASES).toEqual(["/start", "/get-started", "/register"]);
    expect(ALL_PUBLIC_SIGNUP_PATHS).toContain("/signup");
    expect(ALL_PUBLIC_SIGNUP_PATHS).toContain("/start");
  });

  it("keeps invite accept on /accept-invite", () => {
    expect(ACCEPT_INVITE_PATH).toBe("/accept-invite");
  });

  it("builds embeddable signup URLs with optional UTM params", () => {
    expect(buildPublicSignupUrl("https://app.example.com")).toBe(
      "https://app.example.com/signup",
    );
    expect(
      buildPublicSignupUrl("https://app.example.com/", {
        utm_source: "website",
        utm_campaign: "hero",
      }),
    ).toBe("https://app.example.com/signup?utm_source=website&utm_campaign=hero");
    expect(buildPublicSignupPath({ ref: "partner" })).toBe("/signup?ref=partner");
  });
});
