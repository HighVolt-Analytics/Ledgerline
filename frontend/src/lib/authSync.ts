/** Cross-tab auth token sync — same-tenant refresh only; never overwrite another tenant's tab. */

import type { AuthUser } from "@/api/types";
import type { TenantAccountSummary } from "@/lib/authApi";
import { tenantIdFromToken } from "@/lib/authToken";

const CHANNEL = "ledgerline-auth-sync";

export type AuthSyncPayload = {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
  memberships?: TenantAccountSummary[];
};

export function authSyncTenantId(payload: AuthSyncPayload): string | null {
  const fromToken = tenantIdFromToken(payload.access_token);
  if (fromToken) return fromToken;
  const tid = payload.user?.tenant_id;
  return tid ? String(tid) : null;
}

/**
 * Apply cross-tab sync only when the incoming session matches the active tenant.
 * Mismatched tenants are ignored — never mutate current tab user/cache.
 */
export function shouldApplyAuthSync(
  currentTenantId: string | null | undefined,
  payload: AuthSyncPayload,
): boolean {
  const incomingTenantId = authSyncTenantId(payload);
  if (!incomingTenantId) return false;
  const profileTenantId = payload.user?.tenant_id ? String(payload.user.tenant_id) : null;
  // Reject payloads where JWT tenant and profile tenant disagree.
  if (profileTenantId && profileTenantId !== incomingTenantId) return false;
  if (!currentTenantId) return true;
  return currentTenantId === incomingTenantId;
}

export function broadcastAuthSync(payload: AuthSyncPayload): void {
  if (typeof BroadcastChannel === "undefined") return;
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage(payload);
    channel.close();
  } catch {
    /* ignore */
  }
}

export function subscribeAuthSync(handler: (payload: AuthSyncPayload) => void): () => void {
  if (typeof BroadcastChannel === "undefined") return () => undefined;
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (event: MessageEvent<AuthSyncPayload>) => {
      if (event.data?.access_token && event.data?.refresh_token && event.data?.user) {
        handler(event.data);
      }
    };
    return () => channel.close();
  } catch {
    return () => undefined;
  }
}
