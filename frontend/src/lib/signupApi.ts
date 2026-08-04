import { resolveApiBase } from "@/lib/apiBase";
import type { AuthUser } from "@/api/types";

const BASE = resolveApiBase();
const SIGNUP_TOKEN_KEY = "ledgerlink_signup_token";

export type SignupSessionInfo = {
  email: string;
  full_name: string;
  provider: string;
  status: string;
  organization_name?: string | null;
  country?: string | null;
  currency?: string | null;
  industry?: string | null;
  phone?: string | null;
  plan?: string | null;
  identity_via_oauth: boolean;
};

export type SignupPlan = {
  plan: string;
  label: string;
  monthly_credits: number;
  max_users: number;
  monthly_price: number;
  currency_code: string;
  social_integration: boolean;
  email_integration: boolean;
};

export type SignupCompleteResponse = {
  access_token: string;
  refresh_token: string;
  redirect_to: string;
  user: AuthUser;
};

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body.detail ?? body.error?.message;
    if (typeof detail === "string") return detail;
    return res.statusText;
  } catch {
    return res.statusText;
  }
}

function authHeaders(signupToken: string) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${signupToken}`,
  };
}

export function persistSignupToken(token: string) {
  sessionStorage.setItem(SIGNUP_TOKEN_KEY, token);
}

export function getSignupToken(): string | null {
  return sessionStorage.getItem(SIGNUP_TOKEN_KEY);
}

export function clearSignupToken() {
  sessionStorage.removeItem(SIGNUP_TOKEN_KEY);
}

export async function signupRegister(
  email: string,
  password: string,
  fullName: string
): Promise<{ challenge_token: string }> {
  const res = await fetch(`${BASE}/api/signup/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data;
}

export async function signupVerifyOtp(
  challengeToken: string,
  otp: string
): Promise<{ signup_token: string }> {
  const res = await fetch(`${BASE}/api/signup/verify-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${challengeToken}`,
    },
    body: JSON.stringify({ otp }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data;
}

export async function fetchSignupSession(signupToken: string): Promise<SignupSessionInfo> {
  const res = await fetch(`${BASE}/api/signup/session`, {
    headers: { Authorization: `Bearer ${signupToken}` },
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupSessionInfo;
}

export async function signupSetOrganization(
  signupToken: string,
  organizationName: string,
  country: string,
  currency: string,
  industry?: string,
  phone?: string
): Promise<SignupSessionInfo> {
  const res = await fetch(`${BASE}/api/signup/organization`, {
    method: "POST",
    headers: authHeaders(signupToken),
    body: JSON.stringify({
      organization_name: organizationName,
      country,
      currency,
      industry: industry?.trim() || undefined,
      phone: phone?.trim() || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupSessionInfo;
}

export async function fetchSignupPlans(signupToken: string): Promise<SignupPlan[]> {
  const res = await fetch(`${BASE}/api/signup/plans`, {
    headers: { Authorization: `Bearer ${signupToken}` },
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupPlan[];
}

export async function signupSelectPlan(signupToken: string, plan: string): Promise<SignupSessionInfo> {
  const res = await fetch(`${BASE}/api/signup/select-plan`, {
    method: "POST",
    headers: authHeaders(signupToken),
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupSessionInfo;
}

export async function signupCheckout(
  signupToken: string
): Promise<{ checkout_url: string; session_id: string }> {
  const res = await fetch(`${BASE}/api/signup/checkout`, {
    method: "POST",
    headers: authHeaders(signupToken),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data;
}

export async function signupConfirmPayment(
  signupToken: string,
  sessionId: string
): Promise<SignupCompleteResponse> {
  const res = await fetch(`${BASE}/api/signup/confirm-payment?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: authHeaders(signupToken),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupCompleteResponse;
}

export async function signupCompleteStudio(
  signupToken: string,
  sessionId: string
): Promise<SignupCompleteResponse> {
  const res = await fetch(
    `${BASE}/api/signup/complete-studio?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: "POST",
      headers: authHeaders(signupToken),
    }
  );
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupCompleteResponse;
}

export async function signupCompleteFree(signupToken: string): Promise<SignupCompleteResponse> {
  const res = await fetch(`${BASE}/api/signup/complete-free`, {
    method: "POST",
    headers: authHeaders(signupToken),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as SignupCompleteResponse;
}
