import { apiRefreshSession } from "@/lib/authApi";
import { getRefreshToken, persistAuthSuccess } from "@/lib/authSession";
import { setAuthToken, setAuthUser } from "@/api/client";

let inflight: Promise<void> | null = null;

export async function refreshAccessTokenSingleFlight(): Promise<void> {
  if (inflight) {
    await inflight;
    return;
  }
  const refresh = getRefreshToken();
  if (!refresh) throw new Error("No refresh token");

  inflight = (async () => {
    const data = await apiRefreshSession(refresh);
    persistAuthSuccess({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: data.user,
    });
    setAuthToken(data.access_token);
    setAuthUser(data.user);
  })();

  try {
    await inflight;
  } finally {
    inflight = null;
  }
}
