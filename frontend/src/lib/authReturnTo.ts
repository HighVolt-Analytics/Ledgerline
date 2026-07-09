import { homePathForRole } from "@/lib/roles";

const RETURN_TO_PARAM = "returnTo";
const OAUTH_RETURN_TO_KEY = "ledgerline_oauth_return_to";

/** Allow only same-app relative paths after login (blocks open redirects). */
export function sanitizeReturnPath(path: string | null | undefined): string | null {
  const raw = (path ?? "").trim();
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  if (raw.startsWith("/login")) return null;
  return raw;
}

export function readReturnTo(searchParams: URLSearchParams): string | null {
  return sanitizeReturnPath(searchParams.get(RETURN_TO_PARAM));
}

export function buildLoginPathWithReturn(returnPath: string): string {
  const safe = sanitizeReturnPath(returnPath);
  if (!safe) return "/login";
  return `/login?${RETURN_TO_PARAM}=${encodeURIComponent(safe)}`;
}

export function postLoginPathForRole(
  role: string | undefined | null,
  returnTo?: string | null
): string {
  return sanitizeReturnPath(returnTo) ?? homePathForRole(role);
}

export function rememberOAuthReturnTo(returnPath: string | null | undefined): void {
  const safe = sanitizeReturnPath(returnPath);
  if (!safe) {
    sessionStorage.removeItem(OAUTH_RETURN_TO_KEY);
    return;
  }
  sessionStorage.setItem(OAUTH_RETURN_TO_KEY, safe);
}

export function consumeOAuthReturnTo(): string | null {
  const raw = sessionStorage.getItem(OAUTH_RETURN_TO_KEY);
  sessionStorage.removeItem(OAUTH_RETURN_TO_KEY);
  return sanitizeReturnPath(raw);
}

export function readReturnToFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  return readReturnTo(new URLSearchParams(window.location.search));
}
