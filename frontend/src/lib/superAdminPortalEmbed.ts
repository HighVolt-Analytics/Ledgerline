import { resolveApiBase } from "@/lib/apiBase";
import { homePathForRole } from "@/lib/roles";
import { getRouterBasename, withRouterBasename } from "@/lib/routerBasename";
import type { TokenPairResponse } from "@/lib/authApi";

const EMBED_PATH = "/platform/embed";

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

/** Build the public embed URL for a given access token. */
export function buildSuperAdminPortalEmbedUrl(accessToken: string, appBaseUrl?: string): string {
  const base = (appBaseUrl ?? window.location.origin).replace(/\/+$/, "");
  const basename = getRouterBasename() ?? "";
  const path = `${basename}${EMBED_PATH}?accessToken=${encodeURIComponent(accessToken)}`;
  return `${base}${path}`;
}

/** Exchange embed access token for a normal login session. */
export async function apiPortalEmbedLogin(accessToken: string): Promise<TokenPairResponse> {
  const base = resolveApiBase();
  const res = await fetch(`${base}/api/auth/portal-embed/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: accessToken }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const json = await res.json();
  return json.data as TokenPairResponse;
}

/** HTML snippet for an external site button that opens the super-admin portal. */
export function buildSuperAdminPortalEmbedButtonHtml(
  embedUrl: string,
  label = "Open LedgerLink Super Admin"
): string {
  return `<a href="${embedUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

export function superAdminPortalHomePath(): string {
  return withRouterBasename(homePathForRole("super_admin"));
}

export { EMBED_PATH };
