import { useEffect, useRef } from "react";

/** Run callback on an interval while the browser tab is visible. */
export function useVisibilityPolling(
  callback: () => void | Promise<unknown>,
  intervalMs: number,
  enabled = true
) {
  const saved = useRef(callback);
  const intervalRef = useRef(intervalMs);
  saved.current = callback;
  intervalRef.current = intervalMs;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let timer: number | undefined;

    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        timer = window.setTimeout(resolve, ms);
      });

    const loop = async () => {
      while (!cancelled) {
        await wait(Math.max(1000, intervalRef.current));
        if (cancelled) return;
        if (document.visibilityState !== "visible") continue;
        try {
          // Await the tick so a slow /api/matrix (or similar) cannot stack.
          await saved.current();
        } catch {
          // Keep polling even if a tick fails.
        }
      }
    };

    void loop();
    return () => {
      cancelled = true;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [enabled, intervalMs]);
}
