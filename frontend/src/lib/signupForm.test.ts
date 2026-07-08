import { describe, expect, it } from "vitest";

import {
  getSignupDisabledReason,
  isSignupFormComplete,
  isValidEmail,
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

const validInput = {
  fields: validFields,
  industry: "Technology",
  countryCode: "SG",
  selectedPlan: "studio" as const,
  platformBillingEnabled: true,
  billingPlansLoading: false,
  billingPlansError: null,
  busy: false,
};

describe("signupForm", () => {
  it("accepts complete signup fields", () => {
    expect(validateSignupForm(validFields)).toBeNull();
    expect(isSignupFormComplete(validInput)).toBe(true);
  });

  it("rejects missing business name", () => {
    expect(
      getSignupDisabledReason({
        ...validInput,
        fields: { ...validFields, businessName: "  " },
      })
    ).toMatch(/Business name/);
  });

  it("rejects invalid email", () => {
    expect(isValidEmail("not-an-email")).toBe(false);
    expect(
      getSignupDisabledReason({
        ...validInput,
        fields: { ...validFields, email: "not-an-email" },
      })
    ).toBe("Enter a valid email.");
  });

  it("rejects password mismatch", () => {
    expect(
      getSignupDisabledReason({
        ...validInput,
        fields: { ...validFields, confirmPassword: "other" },
      })
    ).toBe("Passwords do not match.");
  });

  it("blocks studio when platform billing is disabled", () => {
    expect(
      getSignupDisabledReason({
        ...validInput,
        platformBillingEnabled: false,
      })
    ).toBe("Stripe billing is not enabled in staging.");
  });

  it("allows studio when platform billing is enabled and form is valid", () => {
    expect(getSignupDisabledReason(validInput)).toBeNull();
  });

  it("uses signup wording for primary CTA labels", () => {
    expect(signupPrimaryCtaLabel("free", false)).toBe("Create free account");
    expect(signupPrimaryCtaLabel("studio", false)).toBe("Continue to Stripe Checkout");
    expect(signupPrimaryCtaLabel("enterprise", false)).toBe("Contact sales");
    expect(signupPrimaryCtaLabel("studio", true)).toBe("Working…");
  });
});
