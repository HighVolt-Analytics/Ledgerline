import { describe, expect, it } from "vitest";

import {
  buildSignupValidationInput,
  EMPTY_SIGNUP_FIELDS,
  getSignupDisabledReason,
  isSignupFormComplete,
  isValidEmail,
  signupPrimaryCtaLabel,
  validateSignupForm,
} from "@/lib/signupForm";

const validFields = {
  businessName: "My Company",
  email: "user@example.com",
  phone: "400 000 000",
  password: "password123",
  confirmPassword: "password123",
};

const validStudioInput = buildSignupValidationInput(validFields, {
  industry: "Technology",
  countryCode: "SG",
  selectedPlan: "studio",
  platformBillingEnabled: true,
  billingPlansLoading: false,
  busy: false,
});

describe("signupForm", () => {
  it("accepts complete signup fields", () => {
    expect(validateSignupForm(validFields)).toBeNull();
    expect(isSignupFormComplete(validStudioInput)).toBe(true);
  });

  it("rejects missing business name", () => {
    expect(
      getSignupDisabledReason({
        ...validStudioInput,
        fields: { ...validFields, businessName: "  " },
      })
    ).toMatch(/Business name/);
  });

  it("rejects invalid email", () => {
    expect(isValidEmail("not-an-email")).toBe(false);
    expect(
      getSignupDisabledReason({
        ...validStudioInput,
        fields: { ...validFields, email: "not-an-email" },
      })
    ).toBe("Enter a valid email.");
  });

  it("rejects password mismatch", () => {
    expect(
      getSignupDisabledReason({
        ...validStudioInput,
        fields: { ...validFields, confirmPassword: "other" },
      })
    ).toBe("Passwords do not match.");
  });

  it("blocks studio when platform billing is disabled", () => {
    expect(
      getSignupDisabledReason({
        ...validStudioInput,
        platformBillingEnabled: false,
      })
    ).toBe("Stripe billing is not enabled in staging.");
  });

  it("enables studio checkout after user fills each field", () => {
    let fields = { ...EMPTY_SIGNUP_FIELDS };

    expect(
      isSignupFormComplete(
        buildSignupValidationInput(fields, {
          industry: "Technology",
          countryCode: "SG",
          selectedPlan: "studio",
          platformBillingEnabled: true,
          billingPlansLoading: false,
          busy: false,
        })
      )
    ).toBe(false);

    fields = { ...fields, businessName: "Typed Business" };
    fields = { ...fields, email: "typed@example.com" };
    fields = { ...fields, phone: "91234567" };
    fields = { ...fields, password: "password123" };
    fields = { ...fields, confirmPassword: "password123" };

    expect(
      isSignupFormComplete(
        buildSignupValidationInput(fields, {
          industry: "Technology",
          countryCode: "SG",
          selectedPlan: "studio",
          platformBillingEnabled: true,
          billingPlansLoading: false,
          busy: false,
        })
      )
    ).toBe(true);
  });

  it("uses signup wording for primary CTA labels", () => {
    expect(signupPrimaryCtaLabel("free", false)).toBe("Create free account");
    expect(signupPrimaryCtaLabel("studio", false)).toBe("Continue to Stripe Checkout");
    expect(signupPrimaryCtaLabel("enterprise", false)).toBe("Contact sales");
    expect(signupPrimaryCtaLabel("studio", true)).toBe("Working…");
  });
});
