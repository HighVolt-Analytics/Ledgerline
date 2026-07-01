/**
 * Public URL prefix for API calls. Endpoint paths include /api (e.g. BASE + /api/auth/login).
 * Staging/preview: /ledgerlink → /ledgerlink/api/...
 * Production root: "" → /api/...
 */
export function resolveApiBase(): string {
  const fromEnv = import.meta.env.VITE_API_BASE;
  if (typeof fromEnv === "string") {
    return fromEnv.trim();
  }
  return "";
}
