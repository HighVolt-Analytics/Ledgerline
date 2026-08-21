import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { createPortal } from "react-dom";
import { getActiveTenantId, getScopedAuthHeadersForToken } from "@/api/client";
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

const STORAGE_KEY_PREFIX = "ledgerlink_setup_checklist_dismissed";

const COMPLETED_STATE: SetupChecklistState = {
  complete: true,
  show: false,
  progress: 100,
  items: [],
};

function checklistStorageKey(): string {
  return `${STORAGE_KEY_PREFIX}:${getActiveTenantId() ?? "none"}`;
}

function isChecklistDismissed(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    if (localStorage.getItem(checklistStorageKey()) === "complete") return true;
    return localStorage.getItem(STORAGE_KEY_PREFIX) === "complete";
  } catch {
    return false;
  }
}

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

  const refresh = useCallback(async (opts?: { force?: boolean }) => {
    if (!accessToken) {
      setState(null);
      return;
    }
    const storageKey = checklistStorageKey();
    if (!opts?.force && isChecklistDismissed()) {
      setState(COMPLETED_STATE);
      setExpanded(false);
      return;
    }
    setLoading(true);
    try {
      const next = await fetchChecklist(accessToken);
      setState(next);
      if (next.complete) {
        const alreadyComplete = localStorage.getItem(storageKey) === "complete";
        localStorage.setItem(storageKey, "complete");
        setExpanded(false);
        if (!alreadyComplete) {
          await fetch(`${resolveApiBase()}/api/tenants/current/setup-checklist/complete`, {
            method: "POST",
            headers: getScopedAuthHeadersForToken(accessToken),
          });
        }
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
    const handler = () => void refresh({ force: true });
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

  // Minimized "Get set up" until required steps reach 100%, then the widget is removed.

  const items = state?.items ?? [];
  const doneCount = items.filter((i) => i.done && !i.optional).length;
  const totalRequired = items.filter((i) => !i.optional).length;
  const nextRequired = items.find((i) => !i.done && !i.optional) ?? items.find((i) => !i.done) ?? null;
  const progressPct =
    totalRequired > 0
      ? Math.round((doneCount / totalRequired) * 100)
      : state?.progress ?? (loading ? 0 : 0);

  const isComplete =
    state?.complete === true ||
    state?.show === false ||
    (totalRequired > 0 && doneCount >= totalRequired) ||
    progressPct >= 100;

  const locallyDismissed = isChecklistDismissed();

  // Hide permanently once required setup hits 100%.
  if (locallyDismissed || isComplete) {
    return null;
  }

  const ringSize = 34;
  const ringStroke = 4;
  const r = (ringSize - ringStroke) / 2;
  const c = 2 * Math.PI * r;
  const dash = (progressPct / 100) * c;

  const ui = (
    <div className="onboarding-checklist-anchor">
      {expanded ? (
        <div className="onboarding-get-started-surface onboarding-checklist-panel">
          <div className="onboarding-get-started-surface__header px-4 py-3 border-b">
            <div className="onboarding-checklist-panel__header-row">
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
            <div className="onboarding-checklist-panel__progress-row">
              <div className="onboarding-get-started-surface__track onboarding-checklist-panel__progress-track">
                <div
                  className="onboarding-checklist-panel__progress-fill"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="onboarding-get-started-surface__muted onboarding-checklist-panel__progress-label tnum">
                {progressPct}%
              </div>
            </div>
          </div>
          <ul className="onboarding-checklist-panel__list onboarding-get-started-surface__divide">
            {items.length === 0 ? (
              <li className="onboarding-get-started-surface__muted px-4 py-3 text-sm">
                {loading ? "Loading checklist…" : "No setup steps to show right now."}
              </li>
            ) : (
              items.map((item) => (
                <li key={item.id}>
                  <Link
                    to={withRouterBasename(item.route)}
                    className="onboarding-get-started-surface__row onboarding-checklist-panel__item-link"
                    onClick={() => setExpanded(false)}
                  >
                    <span className="onboarding-checklist-panel__item-main">
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
              ))
            )}
          </ul>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="onboarding-get-started-surface onboarding-checklist-trigger"
        >
          <div className="onboarding-checklist-trigger__row">
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
