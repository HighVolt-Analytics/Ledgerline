import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Building2, ChevronDown, Code2, Moon, Pin, PinOff, Settings2, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Logo, LogoBlock } from "@/components/Logo";
import { TenantSwitcher } from "@/components/TenantSwitcher";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";

const PIN_STORAGE_KEY = "ledgerline_superadmin_sidebar_pinned";

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function SuperAdminLayout() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [primaryPinned, setPrimaryPinned] = useState(() => {
    try {
      return localStorage.getItem(PIN_STORAGE_KEY) !== "false";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(PIN_STORAGE_KEY, String(primaryPinned));
    } catch {
      /* ignore */
    }
  }, [primaryPinned]);

  return (
    <div
      className={cn(
        "app-shell grid-cols-1",
        !primaryPinned && "app-shell--primary-collapsed"
      )}
    >
      <aside className="primary-sidebar">
        <div className="primary-sidebar__header">
          <div className="primary-sidebar__logo">
            <span className="primary-sidebar__logo-mark">
              <Logo size={18} />
            </span>
            <div className="primary-sidebar__logo-label flex flex-col min-w-0 leading-none">
              <span className="font-semibold text-[13px] tracking-tight truncate">Platform</span>
            </div>
          </div>
          <button
            type="button"
            className="primary-sidebar__pin"
            onClick={() => setPrimaryPinned((p) => !p)}
            aria-label={primaryPinned ? "Unpin sidebar" : "Pin sidebar"}
          >
            {primaryPinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
          </button>
        </div>
        <nav className="primary-sidebar__nav">
          <button type="button" className="primary-sidebar__topic primary-sidebar__topic--active">
            <Building2 className="primary-sidebar__topic-icon" />
            <span className="primary-sidebar__topic-label">Clients</span>
          </button>
        </nav>
      </aside>

      <div className="app-shell__cards">
      <aside className="secondary-sidebar">
        <div className="secondary-sidebar__header">
          <h2 className="secondary-sidebar__title">Super Admin</h2>
        </div>
        <nav className="secondary-sidebar__nav">
          <div className="secondary-sidebar__list">
            <NavLink
              to="/platform/clients"
              className={({ isActive }) =>
                cn("secondary-nav-item", isActive && "secondary-nav-item--active")
              }
              data-testid="nav-clients"
            >
              <span className="secondary-nav-item__label">Clients</span>
            </NavLink>
            <NavLink
              to="/platform/credit-settings"
              className={({ isActive }) =>
                cn("secondary-nav-item", isActive && "secondary-nav-item--active")
              }
              data-testid="nav-credit-settings"
            >
              <Settings2 className="h-4 w-4 shrink-0" />
              <span className="secondary-nav-item__label">Credit settings</span>
            </NavLink>
            <NavLink
              to="/platform/developer-port"
              className={({ isActive }) =>
                cn("secondary-nav-item", isActive && "secondary-nav-item--active")
              }
              data-testid="nav-developer-port"
            >
              <Code2 className="h-4 w-4 shrink-0" />
              <span className="secondary-nav-item__label">Developer Port</span>
            </NavLink>
          </div>
        </nav>
      </aside>

      <div className="app-workspace">
        <header className="app-workspace__header">
          <div className="md:hidden text-primary">
            <LogoBlock collapsed />
          </div>
          <Badge variant="outline" className="font-medium">
            Platform Console
          </Badge>
          <div className="flex-1" />
          <TenantSwitcher />
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <div className="relative">
            <button
              type="button"
              className="flex items-center gap-2 rounded-lg pl-1 pr-2 py-1 hover-elevate"
              onClick={() => setUserMenuOpen((o) => !o)}
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-medium">
                {user ? initials(user.full_name) : "?"}
              </span>
              <span className="hidden sm:block text-sm font-medium">
                {user?.full_name ?? "Super Admin"}
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div className="absolute right-0 top-full mt-1 z-50 w-52 rounded-lg border border-border bg-popover p-1 shadow-float text-sm">
                  <div className="px-2 py-1.5">
                    <div className="font-medium">{user?.full_name}</div>
                    <div className="text-xs text-muted-foreground">Super Admin</div>
                  </div>
                  <div className="my-1 h-px bg-border" />
                  <button
                    type="button"
                    className="w-full text-left px-2 py-1.5 rounded-md hover:bg-accent text-destructive"
                    onClick={() => {
                      setUserMenuOpen(false);
                      logout();
                      navigate("/login");
                    }}
                  >
                    Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="app-workspace__main">
          <div className="app-workspace__scroll">
            <Outlet />
          </div>
        </main>

        <div className="app-workspace__portal" data-app-workspace-portal />
      </div>
      </div>
    </div>
  );
}
