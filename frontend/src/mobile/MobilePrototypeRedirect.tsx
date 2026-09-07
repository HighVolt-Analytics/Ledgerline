import { useEffect } from "react";

/**
 * After auth (/m is ProtectedRoute + TenantRoute), send the browser to the
 * exact static Mobile Prototype (UI-only until API wiring).
 * Source of truth: frontend/public/mobile/
 */
export function MobilePrototypeRedirect() {
  useEffect(() => {
    const base = import.meta.env.BASE_URL || "/";
    const normalized = base.endsWith("/") ? base : `${base}/`;
    window.location.replace(`${normalized}mobile/index.html`);
  }, []);

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        fontFamily: "system-ui, sans-serif",
        fontSize: 14,
        color: "#6b7280",
      }}
    >
      Opening mobile prototype…
    </div>
  );
}
