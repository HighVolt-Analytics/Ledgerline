import Tracker from "@openreplay/tracker";
import trackerAssist from "@openreplay/tracker-assist";

declare global {
  interface Window {
    __OPENREPLAY__?: Tracker;
  }
}

function envString(key: keyof ImportMetaEnv): string {
  const value = import.meta.env[key];
  return typeof value === "string" ? value.trim() : "";
}

function envBool(key: keyof ImportMetaEnv, fallback: boolean): boolean {
  const raw = envString(key).toLowerCase();
  if (!raw) return fallback;
  return raw === "1" || raw === "true" || raw === "yes";
}

function envInt(key: keyof ImportMetaEnv): number | undefined {
  const raw = envString(key);
  if (!raw) return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

const PROJECT_KEY = envString("VITE_OPEN_REPLAY_PROJECT_KEY");

let tracker: Tracker | null = null;
let started = false;
/** After a hard failure, skip further OpenReplay work for this page load. */
let disabled = false;

function logOpenReplayError(message: string): void {
  console.error(`[OpenReplay] ${message}`);
}

function disableOpenReplay(message: string): void {
  disabled = true;
  started = false;
  tracker = null;
  try {
    delete window.__OPENREPLAY__;
  } catch {
    window.__OPENREPLAY__ = undefined;
  }
  logOpenReplayError(message);
}

function buildTrackerOptions(): ConstructorParameters<typeof Tracker>[0] | null {
  if (!PROJECT_KEY) return null;

  const options: ConstructorParameters<typeof Tracker>[0] = {
    projectKey: PROJECT_KEY,
  };

  const ingestPoint = envString("VITE_OPEN_REPLAY_INGEST_POINT");
  if (ingestPoint) options.ingestPoint = ingestPoint;

  const defaultInputMode = envInt("VITE_OPEN_REPLAY_DEFAULT_INPUT_MODE");
  if (defaultInputMode === 0 || defaultInputMode === 1 || defaultInputMode === 2) {
    options.defaultInputMode = defaultInputMode;
  }

  if (envString("VITE_OPEN_REPLAY_OBSCURE_TEXT_NUMBERS")) {
    options.obscureTextNumbers = envBool("VITE_OPEN_REPLAY_OBSCURE_TEXT_NUMBERS", false);
  }

  if (envString("VITE_OPEN_REPLAY_OBSCURE_TEXT_EMAILS")) {
    options.obscureTextEmails = envBool("VITE_OPEN_REPLAY_OBSCURE_TEXT_EMAILS", true);
  }

  const inlineCss = envInt("VITE_OPEN_REPLAY_INLINE_CSS");
  if (inlineCss !== undefined) {
    options.inlineCss = inlineCss;
  }

  // Only force insecure mode when explicitly set (needed for http://localhost).
  if (envString("VITE_OPEN_REPLAY_DISABLE_SECURE_MODE")) {
    options.__DISABLE_SECURE_MODE = envBool(
      "VITE_OPEN_REPLAY_DISABLE_SECURE_MODE",
      false
    );
  }

  return options;
}

export function getOpenReplayTracker(): Tracker | null {
  return tracker;
}

export function initOpenReplay(): Tracker | null {
  try {
    if (typeof window === "undefined" || disabled) return null;
    if (tracker) return tracker;

    const options = buildTrackerOptions();
    if (!options) {
      disableOpenReplay(
        "disabled — VITE_OPEN_REPLAY_PROJECT_KEY is missing or empty."
      );
      return null;
    }

    const instance = new Tracker(options);

    if (envBool("VITE_OPEN_REPLAY_ASSIST_ENABLED", true)) {
      try {
        instance.use(trackerAssist());
      } catch {
        logOpenReplayError("assist plugin failed to load; continuing without it.");
      }
    }

    tracker = instance;
    window.__OPENREPLAY__ = instance;
    return instance;
  } catch {
    disableOpenReplay(
      "init failed — project key may be invalid or expired. App will continue without session recording."
    );
    return null;
  }
}

/** Starts OpenReplay. Never throws — failures only log and leave the app running. */
export async function startOpenReplay(userID?: string): Promise<void> {
  try {
    if (disabled) return;

    const instance = initOpenReplay();
    if (!instance) return;

    if (started) {
      if (userID) identifyOpenReplayUser(userID);
      return;
    }

    started = true;
    const result = await instance.start(userID ? { userID } : undefined);

    if (result && "success" in result && result.success === false) {
      disableOpenReplay(
        "start rejected — project key may be expired or invalid. App will continue without session recording."
      );
      return;
    }

    if (userID) identifyOpenReplayUser(userID);
    if (import.meta.env.DEV) {
      console.log("[OpenReplay] started");
    }
  } catch {
    disableOpenReplay(
      "start failed — project key may be expired/invalid, or OpenReplay is unreachable. App will continue without session recording."
    );
  }
}

/** Identify the recorded user. Never throws. */
export function identifyOpenReplayUser(
  userID: string | null | undefined,
  metadata?: Record<string, string>
): void {
  try {
    if (disabled || !userID) return;
    const instance = tracker ?? window.__OPENREPLAY__;
    if (!instance) return;

    instance.identify(String(userID));
    if (metadata) {
      for (const [key, value] of Object.entries(metadata)) {
        if (value) instance.setMetadata(key, value);
      }
    }
  } catch {
    logOpenReplayError(
      "identify failed — session may be inactive or project key expired. App will continue."
    );
  }
}
