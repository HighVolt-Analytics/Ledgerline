import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { createPortal } from "react-dom";
import { getScopedAuthHeadersForToken } from "@/api/client";
import { resolveApiBase } from "@/lib/apiBase";
import { cn } from "@/lib/cn";
import { withRouterBasename } from "@/lib/routerBasename";

export type SetupChecklistItem = {
  id: string;
  label: string;
  group: string;
  done: boolean;
  route: string;
  optional?: boolean;
};

type SetupChecklistState = {
  complete: boolean;
  show: boolean;
  progress: number;
  items: SetupChecklistItem[];
};

type OnboardingChecklistContextValue = {
  state: SetupChecklistState | null;
  loading: boolean;
  refresh: () => Promise<void>;
  expanded: boolean;
  setExpanded: (open: boolean) => void;
};

const OnboardingChecklistContext = createContext<OnboardingChecklistContextValue | null>(null);

const STORAGE_KEY = "ledgerlink_setup_checklist_dismissed";

async function fetchChecklist(accessToken: string): Promise<SetupChecklistState> {
  const res = await fetch(`${resolveApiBase()}/api/tenants/current/setup-checklist`, {
    headers: getScopedAuthHeadersForToken(accessToken),
  });
  if (!res.ok) throw new Error("Failed to load setup checklist");
  const json = await res.json();
  return json.data as SetupChecklistState;
}

export function OnboardingChecklistProvider({
  accessToken,
  children,
}: {
  accessToken: string | null;
  children: ReactNode;
}) {
  const [state, setState] = useState<SetupChecklistState | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    if (!accessToken) {
      setState(null);
      return;
    }
    setLoading(true);
    try {
      const next = await fetchChecklist(accessToken);
      setState(next);
      if (next.complete) {
        localStorage.setItem(STORAGE_KEY, "complete");
        await fetch(`${resolveApiBase()}/api/tenants/current/setup-checklist/complete`, {
          method: "POST",
          headers: getScopedAuthHeadersForToken(accessToken),
        });
      }
    } catch {
      setState(null);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const handler = () => void refresh();
    window.addEventListener("ledgerlink:onboarding-refresh", handler);
    return () => window.removeEventListener("ledgerlink:onboarding-refresh", handler);
  }, [refresh]);

  const value = useMemo(
    () => ({ state, loading, refresh, expanded, setExpanded }),
    [state, loading, refresh, expanded]
  );

  return (
    <OnboardingChecklistContext.Provider value={value}>{children}</OnboardingChecklistContext.Provider>
  );
}

export function useOnboardingChecklist() {
  const ctx = useContext(OnboardingChecklistContext);
  if (!ctx) {
    throw new Error("useOnboardingChecklist must be used within OnboardingChecklistProvider");
  }
  return ctx;
}

export function notifyOnboardingStatusRefresh() {
  window.dispatchEvent(new Event("ledgerlink:onboarding-refresh"));
}

export function OnboardingChecklistWidget() {
  const { state, loading, expanded, setExpanded } = useOnboardingChecklist();

  // Always render the minimized "Get started" button so it never disappears due to
  // transient loading / API errors. When state is unavailable we show 0% until it loads.
  // Note: we intentionally do NOT hide the minimized button based on `state.show`.
  // The server can still choose to hide the expanded panel contents by returning no items.

  const items = state?.items ?? [];
  const doneCount = items.filter((i) => i.done && !i.optional).length;
  const totalRequired = items.filter((i) => !i.optional).length;
  const nextRequired = items.find((i) => !i.done && !i.optional) ?? items.find((i) => !i.done) ?? null;
  const progressPct =
    totalRequired > 0
      ? Math.round((doneCount / totalRequired) * 100)
      : state?.progress ?? (loading ? 0 : 0);

  const ringSize = 34;
  const ringStroke = 4;
  const r = (ringSize - ringStroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = (progressPct / 100) * c;

  const ui = (
    <div
      className="fixed bottom-4 right-4 z-40 max-w-[calc(100vw-2rem)]"
      // Fallback styles so the button is visible even if Tailwind isn't generating CSS.
      style={{ position: "fixed", right: 16, bottom: 16, zIndex: 40, maxWidth: "calc(100vw - 2rem)" }}
    >
      {expanded ? (
        <div className="onboarding-get-started-surface w-80 rounded-xl border shadow-lg overflow-hidden">
          <div className="onboarding-get-started-surface__header px-4 py-3 border-b">
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="onboarding-get-started-surface__muted text-sm hover:opacity-80"
                onClick={() => setExpanded(false)}
                aria-label="Back"
                title="Back"
              >
                ‹
              </button>
              <div className="flex-1 text-left text-sm font-semibold tracking-tight">
                Getting started
              </div>
              <button
                type="button"
                className="onboarding-get-started-surface__muted text-sm hover:opacity-80"
                onClick={() => setExpanded(false)}
                aria-label="Close"
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="mt-2 flex items-center gap-3">
              <div className="onboarding-get-started-surface__track flex-1 h-2 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${progressPct}%`, backgroundColor: "hsl(var(--nav-accent))" }}
                />
              </div>
              <div className="onboarding-get-started-surface__muted text-xs tnum w-10 text-right">
                {progressPct}%
              </div>
            </div>
          </div>
          <ul className="max-h-72 overflow-y-auto onboarding-get-started-surface__divide">
            {(state?.items ?? []).map((item) => (
              <li key={item.id}>
                <Link
                  to={withRouterBasename(item.route)}
                  className="onboarding-get-started-surface__row flex items-start justify-between gap-3 px-4 py-2.5 text-sm"
                  onClick={() => setExpanded(false)}
                >
                  <span className="min-w-0 flex items-start gap-2">
                    <span
                      className={item.done ? "text-[hsl(var(--nav-accent))]" : "onboarding-get-started-surface__muted"}
                      aria-hidden
                    >
                      {item.done ? "●" : "○"}
                    </span>
                    <span className={cn("min-w-0", item.done && "onboarding-get-started-surface__muted line-through")}>
                      {item.label}
                      {item.optional ? " (optional)" : ""}
                    </span>
                  </span>
                  <span className="onboarding-get-started-surface__muted" aria-hidden>
                    ›
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="onboarding-get-started-surface inline-flex w-[260px] flex-col items-stretch gap-2 rounded-xl border px-4 py-3 shadow-lg hover:opacity-95"
          style={{
            display: "inline-flex",
            width: 260,
            padding: "12px 16px",
            borderRadius: 14,
            boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
          }}
        >
          <div className="flex items-center gap-3">
            <svg
              width={18}
              height={18}
              viewBox={`0 0 ${ringSize} ${ringSize}`}
              aria-hidden
              className="shrink-0"
            >
              <circle
                cx={ringSize / 2}
                cy={ringSize / 2}
                r={r}
                fill="none"
                stroke="hsl(var(--muted-foreground) / 0.25)"
                strokeWidth={ringStroke}
              />
              <circle
                cx={ringSize / 2}
                cy={ringSize / 2}
                r={r}
                fill="none"
                stroke="hsl(var(--nav-accent))"
                strokeWidth={ringStroke}
                strokeLinecap="round"
                strokeDasharray={`${dash} ${c - dash}`}
                transform={`rotate(-90 ${ringSize / 2} ${ringSize / 2})`}
              />
            </svg>
            <span className="flex-1 text-left text-sm font-semibold tracking-tight">
              Get set up
            </span>
            <span
              aria-hidden
              className="onboarding-get-started-surface__muted"
              style={{ fontSize: 16, lineHeight: 1 }}
              title="Expand"
            >
              ⌃
            </span>
          </div>

          {nextRequired && (
            <div className="onboarding-get-started-surface__muted text-left text-xs leading-snug">
              {nextRequired.label}
            </div>
          )}
        </button>
      )}
    </div>
  );

  // Ensure bottom-right anchoring regardless of scroll containers/transforms.
  return typeof document !== "undefined" ? createPortal(ui, document.body) : ui;
}
