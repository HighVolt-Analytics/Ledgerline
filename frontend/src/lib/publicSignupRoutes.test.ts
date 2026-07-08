import { describe, expect, it } from "vitest";
import {
  ACCEPT_INVITE_PATH,
  PUBLIC_SIGNUP_PATH,
} from "@/lib/publicSignupRoutes";

describe("public signup routes", () => {
  it("uses /signup for token-less public self-serve signup", () => {
    expect(PUBLIC_SIGNUP_PATH).toBe("/signup");
  });

  it("keeps invite accept on /accept-invite", () => {
    expect(ACCEPT_INVITE_PATH).toBe("/accept-invite");
  });
});
