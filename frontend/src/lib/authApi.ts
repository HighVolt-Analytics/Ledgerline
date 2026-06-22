import { LEDGERLINK_BASENAME } from "@/lib/routerBasename";
import type { AuthUser } from "@/api/types";

const BASE =
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.PROD ? LEDGERLINK_BASENAME : "");

export type TenantAccountSummary = {
  user_id: number;
  tenant_id: number;
  tenant_name: string;
  tenant_slug: string;
  role: string;
};

export type LoginChallengeResponse = {
  challenge_token: string;
  message: string;
};

export type VerifyOtpResponse = {
  multi_tenant: boolean;
  access_token?: string;
  refresh_token?: string;
  tenant_select_token?: string;
  accounts?: TenantAccountSummary[];
  user?: AuthUser;
};

export type TokenPairResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
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

export async function apiLogin(email: string, password: string): Promise<LoginChallengeResponse> {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as LoginChallengeResponse;
}

export async function apiVerifyOtp(
  challengeToken: string,
  otp: string
): Promise<VerifyOtpResponse> {
  const res = await fetch(`${BASE}/api/auth/verify-otp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${challengeToken}`,
    },
    body: JSON.stringify({ otp }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as VerifyOtpResponse;
}

export async function apiResendOtp(challengeToken: string): Promise<LoginChallengeResponse> {
  const res = await fetch(`${BASE}/api/auth/resend-otp`, {
    method: "POST",
    headers: { Authorization: `Bearer ${challengeToken}` },
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as LoginChallengeResponse;
}

export async function apiSelectTenant(
  tenantSelectToken: string,
  tenantId: number
): Promise<TokenPairResponse> {
  const res = await fetch(`${BASE}/api/auth/select-tenant`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${tenantSelectToken}`,
    },
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as TokenPairResponse;
}

export async function apiRefreshSession(refreshToken: string): Promise<TokenPairResponse> {
  const res = await fetch(`${BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as TokenPairResponse;
}
