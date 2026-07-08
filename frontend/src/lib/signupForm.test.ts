import { describe, expect, it } from "vitest";

import {
  isSignupFormComplete,
  signupPrimaryCtaLabel,
  validateSignupForm,
} from "@/lib/signupForm";

const validFields = {
  businessName: "Acme Pty Ltd",
  email: "accounts@acme.com",
  phone: "400 000 000",
  password: "password123",
  confirmPassword: "password123",
};

describe("signupForm", () => {
  it("accepts complete signup fields", () => {
    expect(validateSignupForm(validFields)).toBeNull();
    expect(isSignupFormComplete(validFields)).toBe(true);
  });

  it("rejects missing business name", () => {
    expect(
      validateSignupForm({ ...validFields, businessName: "  " })
    ).toMatch(/Business name/);
  });

  it("rejects password mismatch", () => {
    expect(
      validateSignupForm({ ...validFields, confirmPassword: "other" })
    ).toMatch(/do not match/);
  });

  it("uses signup wording for primary CTA labels", () => {
    expect(signupPrimaryCtaLabel("free", false)).toBe("Create free account");
    expect(signupPrimaryCtaLabel("studio", false)).toBe("Continue to Stripe Checkout");
    expect(signupPrimaryCtaLabel("enterprise", false)).toBe("Contact sales");
    expect(signupPrimaryCtaLabel("studio", true)).toBe("Working…");
  });
});
