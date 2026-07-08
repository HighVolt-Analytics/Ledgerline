import type { PlanId } from "@/lib/pricingPlans";

export type SignupFormFields = {
  businessName: string;
  email: string;
  phone: string;
  password: string;
  confirmPassword: string;
};

export type SignupValidationInput = {
  fields: SignupFormFields;
  industry: string;
  countryCode: string;
  selectedPlan: PlanId;
  platformBillingEnabled: boolean | null;
  billingPlansLoading: boolean;
  busy: boolean;
};

export const EMPTY_SIGNUP_FIELDS: SignupFormFields = {
  businessName: "",
  email: "",
  phone: "",
  password: "",
  confirmPassword: "",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

export function validateSignupForm(fields: SignupFormFields): string | null {
  return getSignupDisabledReason({
    fields,
    industry: "Technology",
    countryCode: "AU",
    selectedPlan: "free",
    platformBillingEnabled: true,
    billingPlansLoading: false,
    busy: false,
  });
}

export function getSignupDisabledReason(input: SignupValidationInput): string | null {
  if (input.busy) {
    return null;
  }

  const { fields } = input;

  if (!fields.businessName.trim()) {
    return "Business name is required.";
  }
  if (!input.industry.trim()) {
    return "Select an industry.";
  }
  if (!input.countryCode.trim()) {
    return "Select a country.";
  }
  if (!fields.email.trim()) {
    return "Email is required.";
  }
  if (!isValidEmail(fields.email)) {
    return "Enter a valid email.";
  }
  if (!fields.phone.trim()) {
    return "Phone number is required.";
  }
  if (!fields.password) {
    return "Password is required.";
  }
  if (fields.password.length < 8) {
    return "Password must be at least 8 characters.";
  }
  if (fields.password !== fields.confirmPassword) {
    return "Passwords do not match.";
  }
  if (!input.selectedPlan) {
    return "Select a plan.";
  }

  if (input.selectedPlan === "studio") {
    if (input.billingPlansLoading) {
      return "Loading billing options…";
    }
    if (input.platformBillingEnabled === false) {
      return "Stripe billing is not enabled in staging.";
    }
  }

  return null;
}

export function isSignupFormComplete(input: SignupValidationInput): boolean {
  return getSignupDisabledReason(input) === null;
}

export function signupPrimaryCtaLabel(plan: PlanId, busy: boolean): string {
  if (busy) return "Working…";
  if (plan === "free") return "Create free account";
  if (plan === "studio") return "Continue to Stripe Checkout";
  return "Contact sales";
}

export function signupPlanHint(plan: PlanId): string | null {
  if (plan === "free") {
    return "Your free account is created immediately — no payment required.";
  }
  if (plan === "studio") {
    return "You will complete subscription payment on Stripe Checkout. Your organisation is created after payment succeeds.";
  }
  if (plan === "enterprise") {
    return "Enterprise plans are set up with our sales team.";
  }
  return null;
}

export function buildSignupValidationInput(
  fields: SignupFormFields,
  options: Omit<SignupValidationInput, "fields">
): SignupValidationInput {
  return { fields, ...options };
}
