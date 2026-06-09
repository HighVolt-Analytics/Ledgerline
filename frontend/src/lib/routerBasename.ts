/** Public app path prefix (no trailing slash). */
export const LEDGERLINK_BASENAME = "/ledgerlink";

/**
 * React Router basename derived from VITE_BASE_PATH.
 * Production default: /ledgerlink. Local dev: undefined (app at /).
 */
export function getRouterBasename(): string | undefined {
  const raw =
    import.meta.env.VITE_BASE_PATH ??
    (import.meta.env.PROD ? `${LEDGERLINK_BASENAME}/` : "/");
  const normalized = raw.replace(/\/+$/, "");
  return normalized || undefined;
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
