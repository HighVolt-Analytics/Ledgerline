/**
 * @vitest-environment happy-dom
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function PollHarness({
  callback,
  intervalMs,
  enabled = true,
}: {
  callback: () => void | Promise<unknown>;
  intervalMs: number;
  enabled?: boolean;
}) {
  useVisibilityPolling(callback, intervalMs, enabled);
  return null;
}

describe("useVisibilityPolling", () => {
  it("does not start the next tick until the previous callback finishes", async () => {
    vi.useFakeTimers();
    let resolveTick: (() => void) | undefined;
    const callback = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveTick = resolve;
        })
    );

    render(<PollHarness callback={callback} intervalMs={1000} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(callback).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveTick?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(callback).toHaveBeenCalledTimes(2);
  });
});
