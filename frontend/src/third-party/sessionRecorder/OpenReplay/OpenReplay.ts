import Tracker from "@openreplay/tracker";
import trackerAssist from "@openreplay/tracker-assist";

declare global {
  interface Window {
    __OPENREPLAY__?: Tracker;
  }
}

const PROJECT_KEY =
  import.meta.env.VITE_OPEN_REPLAY_PROJECT_KEY?.trim() || "VyGAayNuYY1cqHRz29Aa";

let tracker: Tracker | null = null;
let started = false;

export function getOpenReplayTracker(): Tracker | null {
  return tracker;
}

export function initOpenReplay(): Tracker | null {
  if (typeof window === "undefined") return null;
  if (tracker) return tracker;

  tracker = new Tracker({
    projectKey: PROJECT_KEY,
    // 0 - plain, 1 - obscured, 2 - ignored
    defaultInputMode: 2,
    obscureTextNumbers: false,
    obscureTextEmails: true,
    // Required for http://localhost — tracker refuses to start without HTTPS otherwise
    __DISABLE_SECURE_MODE: import.meta.env.DEV,
    // Capture CSS inline so localhost styles work in replays
    inlineCss: 3,
  });

  tracker.use(trackerAssist());
  window.__OPENREPLAY__ = tracker;
  return tracker;
}

export async function startOpenReplay(userID?: string): Promise<void> {
  const instance = initOpenReplay();
  if (!instance || started) {
    if (instance && userID) instance.identify(userID);
    return;
  }

  started = true;
  try {
    const result = await instance.start(userID ? { userID } : undefined);
    if (userID) instance.identify(userID);
    if (import.meta.env.DEV) {
      console.log("[OpenReplay] started", result);
    }
  } catch (err) {
    started = false;
    console.error("[OpenReplay] failed to start", err);
  }
}

/** Identify the recorded user — prefer email (stable, searchable in OpenReplay). */
export function identifyOpenReplayUser(
  userID: string | null | undefined,
  metadata?: Record<string, string>
): void {
  const instance = tracker ?? window.__OPENREPLAY__;
  if (!instance || !userID) return;
  instance.identify(String(userID));
  if (metadata) {
    for (const [key, value] of Object.entries(metadata)) {
      if (value) instance.setMetadata(key, value);
    }
  }
}

