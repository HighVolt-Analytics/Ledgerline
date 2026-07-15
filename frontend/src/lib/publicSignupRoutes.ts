import { withRouterBasename } from "@/lib/routerBasename";

/** Canonical public self-serve signup path (no invite token required). */
export const PUBLIC_SIGNUP_PATH = "/signup";

/** Marketing-friendly aliases that open the same signup wizard. */
export const PUBLIC_SIGNUP_ALIASES = ["/start", "/get-started", "/register"] as const;

export const ALL_PUBLIC_SIGNUP_PATHS = [
  PUBLIC_SIGNUP_PATH,
  ...PUBLIC_SIGNUP_ALIASES,
] as const;

/** Tenant invite accept flow (requires ?token=). */
export const ACCEPT_INVITE_PATH = "/accept-invite";

export type PublicSignupLinkParams = {
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  ref?: string;
};

export function buildPublicSignupSearch(params?: PublicSignupLinkParams): string {
  if (!params) return "";
  const qp = new URLSearchParams();
  if (params.utm_source) qp.set("utm_source", params.utm_source);
  if (params.utm_medium) qp.set("utm_medium", params.utm_medium);
  if (params.utm_campaign) qp.set("utm_campaign", params.utm_campaign);
  if (params.utm_content) qp.set("utm_content", params.utm_content);
  if (params.ref) qp.set("ref", params.ref);
  const qs = qp.toString();
  return qs ? `?${qs}` : "";
}

/** In-app path (includes router basename when deployed under /ledgerlink). */
export function buildPublicSignupPath(params?: PublicSignupLinkParams): string {
  return withRouterBasename(`${PUBLIC_SIGNUP_PATH}${buildPublicSignupSearch(params)}`);
}

/**
 * Absolute URL for embedding on marketing sites, emails, or partner pages.
 * Pass `origin` when building server-side; defaults to current browser origin.
 */
export function buildPublicSignupUrl(
  origin?: string,
  params?: PublicSignupLinkParams,
): string {
  const base = (origin ?? (typeof window !== "undefined" ? window.location.origin : ""))
    .trim()
    .replace(/\/+$/, "");
  return `${base}${buildPublicSignupPath(params)}`;
}

/** Example anchor HTML for external websites. */
export function buildPublicSignupAnchorHtml(
  origin?: string,
  params?: PublicSignupLinkParams & { label?: string },
): string {
  const label = params?.label ?? "Get started with Ledgerlink";
  const href = buildPublicSignupUrl(origin, params);
  return `<a href="${href}">${label}</a>`;
}
