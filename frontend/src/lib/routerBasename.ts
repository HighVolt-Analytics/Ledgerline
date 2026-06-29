/** Public app path prefix (no trailing slash). */
export const LEDGERLINK_BASENAME = "/ledgerlink";

/**
 * React Router basename (no trailing slash). Production always uses /ledgerlink.
 */
export function getRouterBasename(): string | undefined {
  const fromEnv = import.meta.env.VITE_BASE_PATH;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  if (import.meta.env.PROD) {
    return LEDGERLINK_BASENAME;
  }
  return undefined;
}

/**
 * Normalize bare /ledgerlink (no trailing slash) to /ledgerlink/ so Vite asset
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
