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
  billingPlansError: string | null;
  busy: boolean;
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/** Merge React state with live DOM values (handles browser autofill). */
export function readSignupFieldsFromForm(
  form: HTMLFormElement | null,
  state: SignupFormFields
): SignupFormFields {
  if (!form) return state;

  const read = (name: keyof SignupFormFields, fallback: string) => {
    const el = form.elements.namedItem(name);
    if (!(el instanceof HTMLInputElement)) return fallback;
    const domValue = el.value;
    return domValue.length > 0 ? domValue : fallback;
  };

  return {
    businessName: read("businessName", state.businessName),
    email: read("email", state.email),
    phone: read("phone", state.phone),
    password: read("password", state.password),
    confirmPassword: read("confirmPassword", state.confirmPassword),
  };
}

export function validateSignupForm(fields: SignupFormFields): string | null {
  return getSignupDisabledReason({
    fields,
    industry: "placeholder",
    countryCode: "AU",
    selectedPlan: "free",
    platformBillingEnabled: true,
    billingPlansLoading: false,
    billingPlansError: null,
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

/** Safe debug string for staging — never includes password values. */
export function signupDisabledDebugSummary(input: SignupValidationInput): string {
  const { fields } = input;
  return [
    `businessName=${fields.businessName.trim().length > 0}`,
    `industry=${Boolean(input.industry.trim())}`,
    `country=${Boolean(input.countryCode.trim())}`,
    `email=${isValidEmail(fields.email)}`,
    `phone=${fields.phone.trim().length > 0}`,
    `passwordLen=${fields.password.length}`,
    `passwordsMatch=${fields.password === fields.confirmPassword}`,
    `plan=${input.selectedPlan}`,
    `platformBilling=${String(input.platformBillingEnabled)}`,
    `billingLoading=${input.billingPlansLoading}`,
    `busy=${input.busy}`,
  ].join(" · ");
}
