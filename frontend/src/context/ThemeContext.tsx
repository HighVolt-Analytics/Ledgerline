import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const THEME_KEY = "ledgerline_theme";

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") return "light";
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || stored === "light" || stored === "system") return stored;
  } catch {
    /* private browsing */
  }
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "system") return systemTheme();
  return preference;
}

function applyResolved(theme: ResolvedTheme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

function persistPreference(preference: ThemePreference) {
  try {
    localStorage.setItem(THEME_KEY, preference);
  } catch {
    /* ignore */
  }
}

const ThemeContext = createContext<{
  themePreference: ThemePreference;
  theme: ResolvedTheme;
  setThemePreference: (preference: ThemePreference) => void;
  toggleTheme: () => void;
}>({
  themePreference: "light",
  theme: "light",
  setThemePreference: () => {},
  toggleTheme: () => {},
});

export function themePreferenceLabel(preference: ThemePreference, resolved: ResolvedTheme): string {
  if (preference === "system") return "Match system";
  return resolved === "dark" ? "Dark" : "Light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [themePreference, setThemePreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [theme, setTheme] = useState<ResolvedTheme>(() => resolveTheme(readStoredPreference()));

  const setThemePreference = useCallback((preference: ThemePreference) => {
    setThemePreferenceState(preference);
    persistPreference(preference);
    const resolved = resolveTheme(preference);
    setTheme(resolved);
    applyResolved(resolved);
  }, []);

  useEffect(() => {
    const resolved = resolveTheme(themePreference);
    setTheme(resolved);
    applyResolved(resolved);
  }, [themePreference]);

  useEffect(() => {
    if (themePreference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const resolved = resolveTheme("system");
      setTheme(resolved);
      applyResolved(resolved);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [themePreference]);

  return (
    <ThemeContext.Provider
      value={{
        themePreference,
        theme,
        setThemePreference,
        toggleTheme: () =>
          setThemePreference(theme === "dark" ? "light" : "dark"),
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
