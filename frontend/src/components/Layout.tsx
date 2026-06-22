import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Coins,
  CreditCard,
  FolderKanban,
  Grid3x3,
  Upload,
  LayoutDashboard,
  Link2,
  Moon,
  Plug,
  Receipt,
  Search,
  Settings,
  ShoppingCart,
  Sun,
  Users,
  Vault,
  Wallet,
} from "lucide-react";
import { LogoBlock } from "@/components/Logo";
import { TenantSwitcher } from "@/components/TenantSwitcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { useNavBadges } from "@/hooks/useNavBadges";
import { queryClient, queryKeys } from "@/lib/queryClient";
import { cn } from "@/lib/cn";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: "upload" | "approvals" | "team_expenses" | "business_expenses" | "payments";
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
      { to: "/team-expenses", label: "Team Expenses", icon: Receipt, badge: "team_expenses" },
      { to: "/expenses", label: "Expenses Management", icon: Coins, badge: "business_expenses" },
      { to: "/purchases", label: "Purchase Management", icon: ShoppingCart },
      { to: "/matrix", label: "Document Matrix", icon: Grid3x3 },
    ],
  },
  {
    label: "Operations",
    items: [
      { to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" },
      { to: "/dossiers", label: "Dossiers", icon: FolderKanban },
      { to: "/vendors", label: "Vendors", icon: Users },
      { to: "/rules", label: "Rule Book", icon: BookOpen },
    ],
  },
  {
    label: "Finance",
    items: [
      { to: "/payments", label: "Payments", icon: Wallet, badge: "payments" },
      { to: "/ledger-link", label: "Ledger Link", icon: Link2 },
      { to: "/vault", label: "Vault", icon: Vault },
      { to: "/reports", label: "Reports", icon: BarChart3 },
    ],
  },
  {
    label: "Admin",
    items: [
      { to: "/integrations", label: "Integrations", icon: Plug },
      { to: "/billing", label: "Billing & Credits", icon: CreditCard },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

const MOBILE_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
  { to: "/matrix", label: "Matrix", icon: Grid3x3 },
  { to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" },
  { to: "/settings", label: "Settings", icon: Settings },
];

const TRUST = ["SOC 2 Type II", "ISO 27001", "Bank-level encryption", "7-year retention"];

function NavBadge({ children }: { children: React.ReactNode }) {
  return (
    <span className="ml-auto rounded-full bg-sidebar-accent text-sidebar-accent-foreground text-[10px] font-semibold px-1.5 py-0.5 tnum">
      {children}
    </span>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function navTestId(label: string) {
  return `nav-${label.toLowerCase().replace(/\s+|&/g, "-")}`;
}

export function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { data: badges } = useNavBadges();
  const counts = {
    upload: badges?.inbox_count ?? 0,
    approvals: badges?.pending_approval ?? 0,
    team_expenses: badges?.team_expenses_count ?? 0,
    business_expenses: badges?.business_expenses_count ?? 0,
    payments: badges?.payments_queue_count ?? 0,
  };
  const connected = badges?.integrations_connected ?? 0;
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const refreshCounts = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges });
  };

  const renderNavLink = (to: string, label: string, Icon: NavItem["icon"], badge?: NavItem["badge"]) => {
    const active = pathname === to || (to !== "/" && pathname.startsWith(to));
    let badgeEl = null;
    if (badge === "upload" && counts.upload > 0) {
      badgeEl = <NavBadge>{counts.upload}</NavBadge>;
    }
    if (badge === "approvals" && counts.approvals > 0) {
      badgeEl = <NavBadge>{counts.approvals}</NavBadge>;
    }
    if (badge === "team_expenses" && counts.team_expenses > 0) {
      badgeEl = <NavBadge>{counts.team_expenses}</NavBadge>;
    }
    if (badge === "business_expenses" && counts.business_expenses > 0) {
      badgeEl = <NavBadge>{counts.business_expenses}</NavBadge>;
    }
    if (badge === "payments" && counts.payments > 0) {
      badgeEl = <NavBadge>{counts.payments}</NavBadge>;
    }
    return (
      <NavLink
        key={to}
        to={to}
        end={to === "/"}
        data-testid={navTestId(label)}
        className={cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          active
            ? "bg-sidebar-primary text-sidebar-primary-foreground"
            : "text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        )}
      >
        <Icon className="h-[18px] w-[18px] shrink-0" />
        <span className="flex-1 truncate">{label}</span>
        {badgeEl}
      </NavLink>
    );
  };

  return (
    <div className="grid h-[100dvh] w-full grid-cols-1 md:grid-cols-[248px_1fr] overflow-hidden bg-background text-foreground">
      <aside
        className="app-sidebar hidden md:flex flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border overflow-y-auto"
        style={{ overscrollBehavior: "contain" }}
      >
        <div className="px-4 py-4 text-sidebar-foreground border-b border-sidebar-border">
          <LogoBlock />
        </div>
        <nav className="flex-1 px-2 py-3 space-y-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <p className="px-3 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/45">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon, badge }) =>
                  renderNavLink(to, label, Icon, badge)
                )}
              </div>
            </div>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-sidebar-border">
          <div className="flex items-center gap-2 text-[11px] text-sidebar-foreground/55">
            <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--chart-1))]" />
            {connected} integrations connected
          </div>
          <div className="mt-2.5 flex flex-wrap gap-x-2 gap-y-1">
            {TRUST.map((t) => (
              <span key={t} className="text-[10px] text-sidebar-foreground/40">
                {t}
              </span>
            ))}
          </div>
        </div>
      </aside>

      <div className="flex flex-col overflow-hidden min-w-0">
        <header className="flex items-center gap-3 border-b border-border bg-background/95 backdrop-blur px-4 md:px-6 h-14 shrink-0 z-10">
          <div className="md:hidden text-primary">
            <LogoBlock collapsed />
          </div>
          <TenantSwitcher variant="header" showManageActions />
          <TenantSwitcher variant="sidebar" />
          <button
            type="button"
            className="hidden md:flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-card text-sm text-muted-foreground hover-elevate flex-1 max-w-md"
            data-testid="button-global-search"
          >
            <Search className="h-4 w-4" />
            <span className="flex-1 text-left">Search…</span>
            <kbd className="text-[10px] rounded border border-border px-1.5 py-0.5 tnum">
              ⌘K
            </kbd>
          </button>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => navigate("/billing")}
            data-testid="button-credits-badge"
            className="flex items-center gap-1.5 h-9 px-2.5 rounded-md border border-border bg-card text-sm hover-elevate"
          >
            <Coins className="h-4 w-4 text-primary" />
            <span className="tnum font-medium">{(1240).toLocaleString()}</span>
            <span className="hidden sm:inline text-muted-foreground text-xs">credits</span>
          </button>
          <Badge
            variant="outline"
            className="border-[hsl(43_74%_49%/0.5)] text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)] font-medium"
          >
            Sandbox
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            data-testid="button-theme-toggle"
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <div className="relative">
            <button
              type="button"
              className="flex items-center gap-2 rounded-md pl-1 pr-2 py-1 hover-elevate"
              data-testid="button-user-menu"
              onClick={() => setUserMenuOpen((o) => !o)}
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-medium">
                {user ? initials(user.full_name) : "?"}
              </span>
              <span className="hidden sm:block text-sm font-medium">
                {user?.full_name ?? "User"}
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div className="absolute right-0 top-full mt-1 z-50 w-52 rounded-md border border-border bg-popover p-1 shadow-md text-sm">
                  <div className="px-2 py-1.5">
                    <div className="font-medium">{user?.full_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {user?.role} · {user?.org_name}
                    </div>
                  </div>
                  <div className="my-1 h-px bg-border" />
                  <button
                    type="button"
                    className="w-full text-left px-2 py-1.5 rounded-sm hover:bg-accent"
                    onClick={() => {
                      setUserMenuOpen(false);
                      navigate("/settings");
                    }}
                  >
                    Profile settings
                  </button>
                  <button
                    type="button"
                    className="w-full text-left px-2 py-1.5 rounded-sm hover:bg-accent"
                    onClick={() => {
                      setUserMenuOpen(false);
                      navigate("/settings?tab=orgs");
                    }}
                  >
                    Manage organisations
                  </button>
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

        <main
          className="flex-1 overflow-y-auto min-h-0 px-4 md:px-6 py-6"
          style={{ overscrollBehavior: "contain" }}
        >
          <Outlet context={{ refreshCounts }} />
        </main>

        <footer className="shrink-0 border-t border-border bg-background/95 backdrop-blur px-4 md:px-6 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground/70">Ledgerline v4</span>
          {user?.email && <span>{user.email}</span>}
          {TRUST.map((t) => (
            <span key={t}>{t}</span>
          ))}
          <span className="ml-auto">© 2026 Ledgerline · Sandbox environment</span>
        </footer>

        <nav className="md:hidden flex items-center gap-1 overflow-x-auto border-t border-border bg-background px-2 py-2 shrink-0">
          {MOBILE_NAV.map(({ to, label, icon: Icon, badge }) => {
            const active = pathname === to || (to !== "/" && pathname.startsWith(to));
            return (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={cn(
                  "flex flex-col items-center gap-0.5 px-3 py-1 rounded-md text-[10px] whitespace-nowrap",
                  active ? "text-primary" : "text-muted-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
                {badge === "upload" && counts.upload > 0 && (
                  <span className="sr-only">{counts.upload} upload</span>
                )}
              </NavLink>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
