import type { PlanId } from "@/lib/pricingPlans";

export type SignupFormFields = {
  businessName: string;
  email: string;
  phone: string;
  password: string;
  confirmPassword: string;
};

export function validateSignupForm(fields: SignupFormFields): string | null {
  if (!fields.businessName.trim()) {
    return "Business name is required.";
  }
  if (!fields.email.trim()) {
    return "Email is required.";
  }
  if (!fields.phone.trim()) {
    return "Phone number is required.";
  }
  if (fields.password.length < 8) {
    return "Password must be at least 8 characters.";
  }
  if (fields.password !== fields.confirmPassword) {
    return "Passwords do not match.";
  }
  return null;
}

export function isSignupFormComplete(fields: SignupFormFields): boolean {
  return validateSignupForm(fields) === null;
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
