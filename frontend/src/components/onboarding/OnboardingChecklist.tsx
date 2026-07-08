import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getScopedAuthHeadersForToken } from "@/api/client";
import { resolveApiBase } from "@/lib/apiBase";
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
    if (localStorage.getItem(STORAGE_KEY) === "complete") {
      setState({ complete: true, show: false, progress: 100, items: [] });
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

  if (loading && !state) return null;
  if (!state?.show || state.complete) return null;

  const doneCount = state.items.filter((i) => i.done && !i.optional).length;
  const totalRequired = state.items.filter((i) => !i.optional).length;

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 max-w-[calc(100vw-2rem)]">
      {expanded ? (
        <div className="rounded-xl border border-border bg-card shadow-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/40">
            <div>
              <p className="text-sm font-semibold">Get started</p>
              <p className="text-xs text-muted-foreground">
                {doneCount}/{totalRequired} required steps
              </p>
            </div>
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setExpanded(false)}
            >
              Minimize
            </button>
          </div>
          <ul className="max-h-72 overflow-y-auto divide-y divide-border">
            {state.items.map((item) => (
              <li key={item.id}>
                <Link
                  to={withRouterBasename(item.route)}
                  className="flex items-start gap-2 px-4 py-2.5 text-sm hover:bg-muted/50"
                  onClick={() => setExpanded(false)}
                >
                  <span
                    className={
                      item.done
                        ? "text-emerald-600"
                        : "text-muted-foreground"
                    }
                  >
                    {item.done ? "✓" : "○"}
                  </span>
                  <span className={item.done ? "text-muted-foreground line-through" : ""}>
                    {item.label}
                    {item.optional ? " (optional)" : ""}
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
          className="ml-auto flex items-center gap-3 rounded-full border border-border bg-card px-4 py-2 shadow-lg hover:bg-muted/50"
        >
          <span
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border-2 border-primary text-xs font-semibold tnum"
            aria-hidden
          >
            {state.progress}%
          </span>
          <span className="text-sm font-medium">Complete your setup</span>
        </button>
      )}
    </div>
  );
}
