import { useEffect, useRef } from "react";

/** Run callback on an interval while the browser tab is visible. */
export function useVisibilityPolling(
  callback: () => void | Promise<void>,
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

    const tick = () => {
      if (cancelled) return;
      if (document.visibilityState === "visible") {
        void saved.current();
      }
    };

    const schedule = () => {
      if (cancelled) return;
      const waitMs = Math.max(1000, intervalRef.current);
      timer = window.setTimeout(() => {
        tick();
        schedule();
      }, waitMs);
    };

    schedule();
    return () => {
      cancelled = true;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [enabled, intervalMs]);
}
