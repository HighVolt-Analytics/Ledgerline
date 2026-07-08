import { resolveApiBase } from "@/lib/apiBase";
import type { TenantAccountSummary } from "@/lib/authApi";

const BASE = resolveApiBase();

export type OAuthProviders = {
  google: boolean;
  microsoft: boolean;
  microsoft_public_client: boolean;
};

export type OAuthFlowResult = {
  result: string;
  access_token?: string;
  refresh_token?: string;
  signup_token?: string;
  tenant_select_token?: string;
  accounts?: TenantAccountSummary[];
  error?: string;
};

export type MicrosoftPrepare = {
  authorize_url: string;
  pkce_verifier: string;
  client_id: string;
  redirect_uri: string;
  token_url: string;
};

const MS_OAUTH_STORAGE_KEY = "ledgerlink_ms_oauth";

type StoredMicrosoftOAuth = {
  pkce_verifier: string;
  client_id: string;
  redirect_uri: string;
  token_url: string;
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

export function oauthStartUrl(provider: "google" | "microsoft", intent: "login" | "signup"): string {
  if (provider === "google") {
    return `${BASE}/api/auth/oauth/google/start?intent=${intent}`;
  }
  return `${BASE}/api/auth/oauth/microsoft/start?intent=${intent}`;
}

export async function fetchOAuthProviders(): Promise<OAuthProviders> {
  const res = await fetch(`${BASE}/api/auth/oauth/providers`);
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as OAuthProviders;
}

export async function prepareMicrosoftOAuth(intent: "login" | "signup"): Promise<MicrosoftPrepare> {
  const res = await fetch(`${BASE}/api/auth/oauth/microsoft/prepare?intent=${intent}`);
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as MicrosoftPrepare;
}

export function storeMicrosoftOAuthConfig(config: StoredMicrosoftOAuth) {
  sessionStorage.setItem(MS_OAUTH_STORAGE_KEY, JSON.stringify(config));
}

export function loadMicrosoftOAuthConfig(): StoredMicrosoftOAuth | null {
  const raw = sessionStorage.getItem(MS_OAUTH_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredMicrosoftOAuth;
  } catch {
    return null;
  }
}

export function clearMicrosoftOAuthConfig() {
  sessionStorage.removeItem(MS_OAUTH_STORAGE_KEY);
}

export async function startMicrosoftOAuth(intent: "login" | "signup"): Promise<void> {
  const providers = await fetchOAuthProviders();
  if (import.meta.env.DEV) {
    console.info("[oauth] Microsoft providers", providers);
  }
  if (!providers.microsoft_public_client) {
    const url = oauthStartUrl("microsoft", intent);
    if (import.meta.env.DEV) {
      console.info("[oauth] Microsoft confidential flow → backend start", url);
    }
    window.location.href = url;
    return;
  }
  const prepared = await prepareMicrosoftOAuth(intent);
  if (import.meta.env.DEV) {
    console.info("[oauth] Microsoft SPA flow prepare", {
      redirect_uri: prepared.redirect_uri,
      client_id_prefix: prepared.client_id.slice(0, 8),
      token_url: prepared.token_url,
    });
  }
  storeMicrosoftOAuthConfig({
    pkce_verifier: prepared.pkce_verifier,
    client_id: prepared.client_id,
    redirect_uri: prepared.redirect_uri,
    token_url: prepared.token_url,
  });
  window.location.href = prepared.authorize_url;
}

async function readMicrosoftTokenError(tokenRes: Response): Promise<string> {
  try {
    const payload = (await tokenRes.json()) as {
      error?: string;
      error_description?: string;
      error_codes?: number[];
    };
    const code = payload.error ?? "unknown_error";
    const desc = payload.error_description ?? "";
    const codes = payload.error_codes?.join(", ") ?? "";
    return [code, desc, codes ? `codes=${codes}` : ""].filter(Boolean).join(" — ");
  } catch {
    return `${tokenRes.status} ${tokenRes.statusText}`;
  }
}

export async function completeMicrosoftOAuthInBrowser(
  code: string,
  state: string
): Promise<OAuthFlowResult> {
  const config = loadMicrosoftOAuthConfig();
  if (!config) {
    const msg = "Microsoft sign-in session expired — try again";
    console.error("[oauth] Microsoft complete: no sessionStorage config");
    throw new Error(msg);
  }

  if (import.meta.env.DEV) {
    console.info("[oauth] Microsoft browser token exchange", {
      redirect_uri: config.redirect_uri,
      client_id_prefix: config.client_id.slice(0, 8),
      token_url: config.token_url,
    });
  }

  const body = new URLSearchParams({
    client_id: config.client_id,
    code,
    redirect_uri: config.redirect_uri,
    grant_type: "authorization_code",
    code_verifier: config.pkce_verifier,
    scope: "openid profile email offline_access",
  });

  const tokenRes = await fetch(config.token_url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!tokenRes.ok) {
    const detail = await readMicrosoftTokenError(tokenRes);
    console.error("[oauth] Microsoft token exchange failed", {
      status: tokenRes.status,
      detail,
      redirect_uri: config.redirect_uri,
    });
    throw new Error(`Microsoft token exchange failed: ${detail}`);
  }
  const tokenData = (await tokenRes.json()) as { id_token?: string; access_token?: string };
  if (!tokenData.id_token) {
    console.error("[oauth] Microsoft token response missing id_token", tokenData);
    throw new Error("Microsoft did not return an id_token");
  }

  const res = await fetch(`${BASE}/api/auth/oauth/microsoft/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      state,
      id_token: tokenData.id_token,
      access_token: tokenData.access_token,
    }),
  });
  clearMicrosoftOAuthConfig();
  if (!res.ok) {
    const detail = await parseError(res);
    console.error("[oauth] Microsoft /complete failed", { status: res.status, detail });
    throw new Error(detail);
  }
  const json = await res.json();
  const result = json.data as OAuthFlowResult;
  if (import.meta.env.DEV) {
    console.info("[oauth] Microsoft /complete result", { result: result.result, error: result.error });
  }
  return result;
}

export function startGoogleOAuth(intent: "login" | "signup") {
  window.location.href = oauthStartUrl("google", intent);
}
