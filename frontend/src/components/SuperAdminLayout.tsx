import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState, type FocusEvent, type PointerEvent } from "react";
import { Building2, Code2, Pin, PinOff, Settings2 } from "lucide-react";
import { Logo } from "@/components/Logo";
import { ProfileSidebarMenu } from "@/components/ProfileSidebarMenu";
import { useUnpinnedSidebarHover } from "@/hooks/useUnpinnedSidebarHover";
import { cn } from "@/lib/cn";

const PIN_STORAGE_KEY = "ledgerline_superadmin_sidebar_pinned";

const NAV_ITEMS = [
  { to: "/platform/clients", label: "Clients", icon: Building2, testId: "nav-clients" },
  {
    to: "/platform/credit-settings",
    label: "Credit settings",
    icon: Settings2,
    testId: "nav-credit-settings",
  },
  {
    to: "/platform/developer-port",
    label: "Developer Port",
    icon: Code2,
    testId: "nav-developer-port",
  },
] as const;

function pathMatchesItem(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`);
}

function isNavItemActive(pathname: string, to: string): boolean {
  if (!pathMatchesItem(pathname, to)) return false;
  for (const item of NAV_ITEMS) {
    if (
      item.to !== to &&
      item.to.length > to.length &&
      pathMatchesItem(pathname, item.to)
    ) {
      return false;
    }
  }
  // Tenant settings lives under /platform/clients/:id
  if (to === "/platform/clients" && pathname.startsWith("/platform/clients/")) {
    return true;
  }
  return true;
}

function positionSidebarTip(el: HTMLElement) {
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--sidebar-tip-top", `${Math.round(rect.top + rect.height / 2)}px`);
  el.style.setProperty("--sidebar-tip-left", `${Math.round(rect.right + 10)}px`);
}

function onSidebarTipIntent(event: PointerEvent | FocusEvent) {
  const tip = (event.target as HTMLElement | null)?.closest?.("[data-sidebar-tip]");
  if (tip instanceof HTMLElement && tip.dataset.sidebarTip) {
    positionSidebarTip(tip);
  }
}

export function SuperAdminLayout() {
  const { pathname } = useLocation();
  const [sidebarPinned, setSidebarPinned] = useState(() => {
    try {
      return localStorage.getItem(PIN_STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const {
    sidebarHovered,
    setSidebarHovered,
    sidebarRef,
    closeHover,
    onSidebarPointerEnter,
    onSidebarPointerLeave,
    showDismiss,
  } = useUnpinnedSidebarHover(sidebarPinned, pathname);

  useEffect(() => {
    try {
      localStorage.setItem(PIN_STORAGE_KEY, String(sidebarPinned));
    } catch {
      /* ignore */
    }
  }, [sidebarPinned]);

  const sidebarExpanded = sidebarPinned || sidebarHovered;

  const toggleSidebarPin = () => {
    if (sidebarPinned) {
      setSidebarPinned(false);
      setSidebarHovered(false);
      return;
    }
    setSidebarPinned(true);
    setSidebarHovered(true);
  };

  const renderSidebarBody = (iconOnly: boolean) => (
    <>
      <div className="primary-sidebar__header">
        <div className="primary-sidebar__header-brand">
          <div
            className={cn("primary-sidebar__logo", iconOnly && "primary-sidebar__logo--collapsed")}
          >
            <span className="primary-sidebar__logo-mark" aria-hidden={!iconOnly}>
              <Logo size={iconOnly ? 16 : 18} />
            </span>
            {!iconOnly && (
              <div className="primary-sidebar__logo-label flex flex-col min-w-0 leading-none">
                <span className="font-semibold text-[13px] tracking-tight truncate">
                  Ledgerlink
                </span>
              </div>
            )}
          </div>
          {!iconOnly && (
            <button
              type="button"
              className="primary-sidebar__pin"
              onClick={toggleSidebarPin}
              aria-label={sidebarPinned ? "Unpin sidebar" : "Pin sidebar open"}
              aria-pressed={sidebarPinned}
              data-testid="button-sidebar-collapse"
            >
              {sidebarPinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
            </button>
          )}
        </div>
      </div>

      <nav className="primary-sidebar__nav" aria-label="Platform sections">
        {NAV_ITEMS.map(({ to, label, icon: Icon, testId }) => {
          const active = isNavItemActive(pathname, to);
          return (
            <NavLink
              key={to}
              to={to}
              end={to !== "/platform/clients"}
              aria-label={iconOnly ? label : undefined}
              data-sidebar-tip={iconOnly ? label : undefined}
              data-testid={testId}
              className={cn(
                "primary-sidebar__topic",
                iconOnly && "primary-sidebar__topic--icon-only",
                active && "primary-sidebar__topic--active"
              )}
            >
              <Icon className="primary-sidebar__topic-icon" aria-hidden />
              {!iconOnly && <span className="primary-sidebar__topic-label">{label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <div className="primary-sidebar__footer">
        <ProfileSidebarMenu collapsed={iconOnly} showSettings={false} />
      </div>
    </>
  );

  return (
    <div
      className={cn(
        "app-shell app-shell--basic-sidebar grid-cols-1",
        !sidebarPinned && "app-shell--primary-collapsed",
        sidebarPinned && "app-shell--primary-pinned"
      )}
    >
      {showDismiss ? (
        <div
          className="primary-sidebar__dismiss"
          aria-hidden="true"
          data-testid="primary-sidebar-dismiss"
          onPointerEnter={closeHover}
          onPointerDown={closeHover}
        />
      ) : null}
      <aside
        ref={sidebarRef}
        className={cn(
          "primary-sidebar",
          !sidebarPinned && "primary-sidebar--icon-rail",
          !sidebarPinned && sidebarHovered && "primary-sidebar--hover-expanded",
          sidebarPinned && "primary-sidebar--pinned"
        )}
        data-testid="primary-sidebar"
        onPointerEnter={!sidebarPinned ? onSidebarPointerEnter : undefined}
        onPointerLeave={!sidebarPinned ? onSidebarPointerLeave : undefined}
        onPointerOver={!sidebarPinned && !sidebarHovered ? onSidebarTipIntent : undefined}
        onFocusCapture={!sidebarPinned && !sidebarHovered ? onSidebarTipIntent : undefined}
      >
        {sidebarPinned ? (
          renderSidebarBody(false)
        ) : (
          <>
            <div className="primary-sidebar__rail">{renderSidebarBody(true)}</div>
            <div
              className="primary-sidebar__flyout"
              aria-hidden={!sidebarExpanded}
              onPointerLeave={!sidebarPinned ? onSidebarPointerLeave : undefined}
            >
              {renderSidebarBody(false)}
            </div>
          </>
        )}
      </aside>

      <div className="app-shell__cards app-shell__cards--single">
        <div className="app-workspace">
          <main className="app-workspace__main">
            <div className="app-workspace__scroll">
              <Outlet />
            </div>
          </main>

          <footer className="app-workspace__footer flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium text-foreground/70 shrink-0">Ledgerlink Platform</span>
            <span className="ml-auto hidden sm:inline">© 2026 Ledgerlink · Platform console</span>
            <span className="ml-auto sm:hidden">© 2026</span>
          </footer>

          <div className="app-workspace__portal" data-app-workspace-portal />
        </div>
      </div>
    </div>
  );
}
