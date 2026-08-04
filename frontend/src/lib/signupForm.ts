import type { PlanId } from "@/lib/pricingPlans";
import { CURRENCIES, COUNTRIES } from "@/data/orgSetup.tsx";

export type SignupFormFields = {
  businessName: string;
  email: string;
  phone: string;
  password: string;
  confirmPassword: string;
};

export type CatalogWhitelist = {
  countryCodes?: string[];
  currencyCodes?: string[];
};

export type SignupValidationInput = {
  fields: SignupFormFields;
  industry: string;
  countryCode: string;
  currencyCode: string;
  selectedPlan: PlanId;
  platformBillingEnabled: boolean | null;
  billingPlansLoading: boolean;
  busy: boolean;
  countryCodes?: string[];
  currencyCodes?: string[];
};

export const EMPTY_SIGNUP_FIELDS: SignupFormFields = {
  businessName: "",
  email: "",
  phone: "",
  password: "",
  confirmPassword: "",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const FALLBACK_CURRENCY_CODES = new Set(CURRENCIES.map((c) => c.code));
const FALLBACK_COUNTRY_CODES = new Set(COUNTRIES.map((c) => c.code));

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

export function getIdentityDisabledReason(
  fields: Pick<SignupFormFields, "email" | "password" | "confirmPassword">,
  busy: boolean
): string | null {
  if (busy) return null;
  if (!fields.email.trim()) return "Email is required.";
  if (!isValidEmail(fields.email)) return "Enter a valid email.";
  if (!fields.password) return "Password is required.";
  if (fields.password.length < 8) return "Password must be at least 8 characters.";
  if (fields.password !== fields.confirmPassword) return "Passwords do not match.";
  return null;
}

export function getOrganizationDisabledReason(
  fields: Pick<SignupFormFields, "businessName" | "phone">,
  industry: string,
  countryCode: string,
  currencyCode: string,
  busy: boolean,
  catalogs?: CatalogWhitelist
): string | null {
  if (busy) return null;
  if (!fields.businessName.trim()) return "Business name is required.";
  if (!industry.trim()) return "Select an industry.";
  if (!countryCode.trim()) return "Select a country.";
  if (!currencyCode.trim()) return "Select a currency.";
  const countryAllow =
    catalogs?.countryCodes && catalogs.countryCodes.length > 0
      ? new Set(catalogs.countryCodes.map((c) => c.toUpperCase()))
      : FALLBACK_COUNTRY_CODES;
  const currencyAllow =
    catalogs?.currencyCodes && catalogs.currencyCodes.length > 0
      ? new Set(catalogs.currencyCodes.map((c) => c.toUpperCase()))
      : FALLBACK_CURRENCY_CODES;
  if (!countryAllow.has(countryCode.trim().toUpperCase())) {
    return "Select a supported country.";
  }
  if (!currencyAllow.has(currencyCode.trim().toUpperCase())) {
    return "Select a supported currency.";
  }
  if (!fields.phone.trim()) return "Phone number is required.";
  return null;
}

/** @deprecated Use getOrganizationDisabledReason for wizard step 2 */
export function getAccountDetailsDisabledReason(
  fields: SignupFormFields,
  industry: string,
  countryCode: string,
  currencyCode: string,
  busy: boolean,
  catalogs?: CatalogWhitelist
): string | null {
  const identity = getIdentityDisabledReason(fields, busy);
  if (identity) return identity;
  return getOrganizationDisabledReason(
    fields,
    industry,
    countryCode,
    currencyCode,
    busy,
    catalogs
  );
}

export function getPlanActionDisabledReason(
  plan: PlanId,
  input: Omit<SignupValidationInput, "selectedPlan">
): string | null {
  const orgReason = getOrganizationDisabledReason(
    input.fields,
    input.industry,
    input.countryCode,
    input.currencyCode,
    input.busy,
    {
      countryCodes: input.countryCodes,
      currencyCodes: input.currencyCodes,
    }
  );
  if (orgReason) return orgReason;

  if (plan === "studio") {
    if (input.billingPlansLoading) return "Loading billing options…";
    if (input.platformBillingEnabled === false) {
      return "Stripe billing is not enabled. Set STRIPE_PLATFORM_BILLING_ENABLED=true in backend/.env and restart the API server.";
    }
  }

  return null;
}

export function validateSignupForm(fields: SignupFormFields): string | null {
  return getSignupDisabledReason({
    fields,
    industry: "Technology",
    countryCode: "AU",
    currencyCode: "AUD",
    selectedPlan: "free",
    platformBillingEnabled: true,
    billingPlansLoading: false,
    busy: false,
  });
}

export function getSignupDisabledReason(input: SignupValidationInput): string | null {
  return getPlanActionDisabledReason(input.selectedPlan, input);
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
    return "Complete subscription payment on Stripe Checkout. Your organisation is created after payment succeeds.";
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
