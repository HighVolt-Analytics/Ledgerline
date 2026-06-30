/** Staging / preview path prefix when deployed under a subpath. */
export const LEDGERLINK_STAGING_BASENAME = "/ledgerlink";

/**
 * React Router basename (no trailing slash).
 * Driven by VITE_BASE_PATH at build time:
 * - staging/preview: /ledgerlink
 * - production root: unset or /
 */
export function getRouterBasename(): string | undefined {
  const fromEnv = import.meta.env.VITE_BASE_PATH;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    const trimmed = fromEnv.trim().replace(/\/+$/, "");
    return trimmed || undefined;
  }
  return undefined;
}

/**
 * Normalize bare basename URL (no trailing slash) to basename/ so Vite asset
 * URLs and React Router both resolve the dashboard at the index route.
 */
export function normalizeBareBasenameUrl(): void {
  const basename = getRouterBasename();
  if (!basename) return;

  const { pathname, search, hash } = window.location;
  if (pathname === basename) {
    window.history.replaceState(null, "", `${basename}/${search}${hash}`);
  }
}

/** Prefix in-app paths with the public basename (e.g. /ledgerlink on staging). */
export function withRouterBasename(path: string): string {
  const basename = getRouterBasename();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!basename) return normalized;
  if (normalized === "/") return `${basename}/`;
  return `${basename}${normalized}`;
}
