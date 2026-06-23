import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Building2, ChevronDown, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { LogoBlock } from "@/components/Logo";
import { TenantSwitcher } from "@/components/TenantSwitcher";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/cn";

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

  return (
    <div className="grid h-[100dvh] w-full grid-cols-1 md:grid-cols-[248px_1fr] overflow-hidden bg-background text-foreground">
      <aside className="app-sidebar hidden md:flex flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border">
        <div className="px-4 py-4 border-b border-sidebar-border">
          <LogoBlock />
          <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
            Super Admin
          </p>
        </div>
        <nav className="flex-1 px-2 py-3">
          <NavLink
            to="/platform/clients"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-primary text-sidebar-primary-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )
            }
            data-testid="nav-clients"
          >
            <Building2 className="h-[18px] w-[18px] shrink-0" />
            Clients
          </NavLink>
        </nav>
      </aside>

      <div className="flex flex-col overflow-hidden min-w-0">
        <header className="flex items-center gap-3 border-b border-border bg-background/95 backdrop-blur px-4 md:px-6 h-14 shrink-0">
          <div className="md:hidden text-primary">
            <LogoBlock collapsed />
          </div>
          <Badge variant="outline" className="font-medium">
            Platform Console
          </Badge>
          <div className="flex-1" />
          <TenantSwitcher />
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <div className="relative">
            <button
              type="button"
              className="flex items-center gap-2 rounded-md pl-1 pr-2 py-1 hover-elevate"
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
                <div className="absolute right-0 top-full mt-1 z-50 w-52 rounded-md border border-border bg-popover p-1 shadow-md text-sm">
                  <div className="px-2 py-1.5">
                    <div className="font-medium">{user?.full_name}</div>
                    <div className="text-xs text-muted-foreground">Super Admin</div>
                  </div>
                  <div className="my-1 h-px bg-border" />
                  <button
                    type="button"
                    className="w-full text-left px-2 py-1.5 rounded-sm hover:bg-accent text-destructive"
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

        <main className="flex-1 overflow-y-auto min-h-0 px-4 md:px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
