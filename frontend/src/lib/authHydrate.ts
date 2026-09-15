import { ApiError, api } from "@/api/client";
import type { AuthUser } from "@/api/types";
import { fetchMyMemberships, type TenantAccountSummary } from "@/lib/authApi";
import {
  getStoredMemberships,
  getStoredUser,
  persistMemberships,
} from "@/lib/authSession";
import { mergeStoredUserWithToken, userFromToken } from "@/lib/authToken";

export type HydrateMembershipsMode = "always" | "if-empty" | "never";

export type HydrateUserOptions = {
  access: string;
  fetchMemberships?: HydrateMembershipsMode;
  /** When api.me() fails, use JWT claims instead of throwing. */
  fallbackToTokenOnMeFailure?: boolean;
};

export type HydratedSession = {
  user: AuthUser;
  memberships: TenantAccountSummary[];
};

export function bootstrapUserFromAccess(access: string): AuthUser | null {
  const tokenProfile = userFromToken(access);
  const storedUser = getStoredUser();
  if (tokenProfile && storedUser) {
    return mergeStoredUserWithToken(storedUser, tokenProfile);
  }
  return tokenProfile ?? storedUser;
}

export async function hydrateUserAndMemberships(
  options: HydrateUserOptions
): Promise<HydratedSession> {
  const {
    access,
    fetchMemberships = "never",
    fallbackToTokenOnMeFailure = false,
  } = options;

  let memberships = getStoredMemberships();
  const shouldFetchMemberships =
    fetchMemberships === "always" ||
    (fetchMemberships === "if-empty" && memberships.length === 0);

  const resolveUser = async (): Promise<AuthUser> => {
    try {
      return await api.me();
    } catch (err) {
      if (!fallbackToTokenOnMeFailure) throw err;
      // Dead/expired session must not keep a JWT-only user — that storms 401s.
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        throw err;
      }
      const fallback = userFromToken(access);
      if (!fallback) throw err;
      return fallback;
    }
  };

  if (shouldFetchMemberships) {
    const [meSettled, membershipsSettled] = await Promise.allSettled([
      resolveUser(),
      fetchMyMemberships(access),
    ]);

    if (meSettled.status === "rejected") {
      throw meSettled.reason;
    }

    if (membershipsSettled.status === "fulfilled") {
      memberships = membershipsSettled.value;
      persistMemberships(memberships);
    } else if (import.meta.env.DEV) {
      console.warn("[auth] Failed to fetch memberships", membershipsSettled.reason);
    }

    return { user: meSettled.value, memberships };
  }

  return { user: await resolveUser(), memberships };
}
