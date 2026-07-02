/** Cross-tab auth token sync — keeps sessionStorage aligned after refresh in another tab. */

import type { AuthUser } from "@/api/types";
import type { TenantAccountSummary } from "@/lib/authApi";

const CHANNEL = "ledgerline-auth-sync";

export type AuthSyncPayload = {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
  memberships?: TenantAccountSummary[];
};

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
