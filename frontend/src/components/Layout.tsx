import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useMemo, useRef, useState, type FocusEvent, type PointerEvent } from "react";
import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Coins,
  CreditCard,
  FolderKanban,
  LayoutDashboard,
  LayoutGrid,
  Link2,
  PinOff,
  Plug,
  Receipt,
  Search,
  Settings,
  ShoppingCart,
  TrendingUp,
  Upload,
  Users,
  Vault,
  Wallet,
} from "lucide-react";
import { GlobalSearchDialog } from "@/components/GlobalSearchBar";
import { Logo } from "@/components/Logo";
import { NotificationBell } from "@/components/NotificationBell";
import { ProfileSidebarMenu } from "@/components/ProfileSidebarMenu";
import { SettingsSidebarMenu } from "@/components/SettingsSidebarMenu";
import { useAuth } from "@/context/AuthContext";
import { useNavBadges } from "@/hooks/useNavBadges";
import { useCollections } from "@/hooks/useCollections";
import { canAccessNavPath, usePermissions } from "@/hooks/usePermissions";
import type { FlatNavItem } from "@/lib/appNavigation";
import { collectionsOpenCount } from "@/lib/collectionsQueue";
import { canAccessModulePath } from "@/lib/tenantModules";
import { queryClient, queryKeys } from "@/lib/queryClient";
import {
  OnboardingChecklistProvider,
  OnboardingChecklistWidget,
} from "@/components/onboarding/OnboardingChecklist";
import { getAccessToken } from "@/lib/authSession";
import { cn } from "@/lib/cn";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?:
    | "upload"
    | "approvals"
    | "team_expenses"
    | "business_expenses"
    | "sales"
    | "payments"
    | "collections";
  moduleKey?: string;
};

type NavGroup = {
  label: string;
  items: NavItem[];
  /** Nested groups show a header + tree line for sub-items */
  nested?: boolean;
};

const WORKSPACE_GROUPS: NavGroup[] = [
  {
    label: "",
    nested: false,
    items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Documents",
    nested: true,
    items: [
      { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
      { to: "/team-expenses", label: "Team Expenses", icon: Receipt, badge: "team_expenses", moduleKey: "team_expenses" },
      { to: "/expenses", label: "Expenses Management", icon: Coins, badge: "business_expenses", moduleKey: "expenses" },
      { to: "/purchases", label: "Purchase Management", icon: ShoppingCart, moduleKey: "purchase" },
      { to: "/sales", label: "Sales Management", icon: TrendingUp, badge: "sales", moduleKey: "sales" },
    ],
  },
];

const OPERATIONS_GROUPS: NavGroup[] = [
  {
    label: "",
    nested: false,
    items: [{ to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" }],
  },
  {
    label: "Records",
    nested: true,
    items: [
      { to: "/dossiers", label: "Dossiers", icon: FolderKanban, moduleKey: "dossiers" },
      { to: "/vendors", label: "Vendors", icon: Users },
      { to: "/rules", label: "Rule Book", icon: BookOpen, moduleKey: "rule_book" },
    ],
  },
];

const FINANCE_GROUPS: NavGroup[] = [
  {
    label: "Payments",
    nested: true,
    items: [
      { to: "/payments", label: "Payments", icon: Wallet, badge: "payments", moduleKey: "payments" },
      { to: "/collections", label: "Collections", icon: Coins, badge: "collections", moduleKey: "sales" },
      { to: "/ledger-link", label: "Ledger Link", icon: Link2, moduleKey: "ledger_link" },
    ],
  },
  {
    label: "Treasury",
    nested: true,
    items: [
      { to: "/vault", label: "Vault", icon: Vault, moduleKey: "vault" },
      { to: "/reports", label: "Reports", icon: BarChart3, moduleKey: "reports" },
    ],
  },
];

const SETTINGS_GROUPS: NavGroup[] = [
  {
    label: "",
    nested: false,
    items: [
      { to: "/integrations", label: "Integrations", icon: Plug },
      { to: "/billing", label: "Billing & Credits", icon: CreditCard },
      { to: "/settings", label: "Organisation", icon: Settings },
    ],
  },
];

type PrimarySection = {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  groups: NavGroup[];
};

const MAIN_PRIMARY_SECTIONS: PrimarySection[] = [
  { id: "workspace", label: "Workspace", icon: LayoutGrid, groups: WORKSPACE_GROUPS },
  { id: "operations", label: "Operations", icon: FolderKanban, groups: OPERATIONS_GROUPS },
  { id: "finance", label: "Finance", icon: Wallet, groups: FINANCE_GROUPS },
];

const SETTINGS_SECTION: PrimarySection = {
  id: "settings",
  label: "Settings",
  icon: Settings,
  groups: SETTINGS_GROUPS,
};

const ALL_SECTIONS: PrimarySection[] = [...MAIN_PRIMARY_SECTIONS, SETTINGS_SECTION];

const MOBILE_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
  { to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" },
  { to: "/settings", label: "Settings", icon: Settings },
];

const TRUST = ["SOC 2 Type II", "ISO 27001", "Bank-level encryption", "7-year retention"];
const PIN_STORAGE_KEY = "ledgerline_sidebar_pinned";

function navTestId(label: string) {
  return `nav-${label.toLowerCase().replace(/\s+|&/g, "-")}`;
}

function pathMatchesItem(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}

function sectionForPath(pathname: string): string {
  let bestSection = "workspace";
  let bestPathLen = -1;
  for (const section of ALL_SECTIONS) {
    for (const group of section.groups) {
      for (const item of group.items) {
        if (pathMatchesItem(pathname, item.to) && item.to.length > bestPathLen) {
          bestSection = section.id;
          bestPathLen = item.to.length;
        }
      }
    }
  }
  return bestSection;
}

function isNavItemActive(pathname: string, to: string): boolean {
  if (!pathMatchesItem(pathname, to)) return false;
  for (const section of ALL_SECTIONS) {
    for (const group of section.groups) {
      for (const item of group.items) {
        if (
          item.to !== to &&
          item.to.length > to.length &&
          pathMatchesItem(pathname, item.to)
        ) {
          return false;
        }
      }
    }
  }
  return true;
}

function navLinkEnd(to: string): boolean {
  if (to === "/") return true;
  for (const section of ALL_SECTIONS) {
    for (const group of section.groups) {
      for (const item of group.items) {
        if (item.to !== to && item.to.startsWith(`${to}/`)) return true;
      }
    }
  }
  return false;
}

function visibleGroupsForSection(
  section: PrimarySection,
  canShow: (item: NavItem) => boolean
): NavGroup[] {
  return section.groups
    .map((group) => ({
      ...group,
      items: group.items.filter(canShow),
    }))
    .filter((group) => group.items.length > 0);
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

function badgeCount(
  badge: NavItem["badge"],
  counts: Record<string, number>
): number {
  if (!badge) return 0;
  return counts[badge] ?? 0;
}

export function Layout() {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const { data: badges } = useNavBadges();
  const { data: collectionRows = [] } = useCollections();
  const { permissions } = usePermissions();
  const enabledModules = permissions?.enabled_modules;

  const canShowNavItem = (item: NavItem) =>
    canAccessModulePath(item.to, enabledModules, item.moduleKey) &&
    canAccessNavPath(item.to, permissions);

  const counts = {
    upload: badges?.inbox_count ?? 0,
    approvals: badges?.pending_approval ?? 0,
    team_expenses: badges?.team_expenses_count ?? 0,
    business_expenses: badges?.business_expenses_count ?? 0,
    sales: badges?.sales_count ?? 0,
    payments: badges?.payments_queue_count ?? 0,
    collections: badges?.collections_queue_count ?? collectionsOpenCount(collectionRows),
  };
  const [expandedSection, setExpandedSection] = useState<string | null>(() =>
    sectionForPath(pathname)
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const [primaryPinned, setPrimaryPinned] = useState(() => {
    try {
      return localStorage.getItem(PIN_STORAGE_KEY) !== "false";
    } catch {
      return true;
    }
  });
  const sidebarCollapsed = !primaryPinned;
  const prevPathname = useRef(pathname);
  const accessToken = getAccessToken();

  useEffect(() => {
    try {
      localStorage.setItem(PIN_STORAGE_KEY, String(primaryPinned));
    } catch {
      /* ignore */
    }
  }, [primaryPinned]);

  const routeSection = sectionForPath(pathname);

  useEffect(() => {
    const section = sectionForPath(pathname);
    if (prevPathname.current !== pathname) {
      setExpandedSection(section);
    }
    prevPathname.current = pathname;
  }, [pathname]);

  const handleSectionTopicClick = (id: string) => {
    setExpandedSection((prev) => (prev === id ? null : id));
  };

  const shouldShowSectionSubnav = (sectionId: string) => expandedSection === sectionId;

  const visibleSettingsGroups = useMemo(
    () => visibleGroupsForSection(SETTINGS_SECTION, canShowNavItem),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabledModules, permissions]
  );

  const settingsMenuItems = useMemo(
    () =>
      visibleSettingsGroups.flatMap((group) =>
        group.items.map((item) => ({
          to: item.to,
          label: item.label,
          icon: item.icon,
        }))
      ),
    [visibleSettingsGroups]
  );

  const searchableNavItems = useMemo((): FlatNavItem[] => {
    const items: FlatNavItem[] = [];
    for (const section of ALL_SECTIONS) {
      for (const group of section.groups) {
        for (const item of group.items) {
          if (!canShowNavItem(item)) continue;
          items.push({
            to: item.to,
            label: item.label,
            icon: item.icon as FlatNavItem["icon"],
            badge: item.badge,
            moduleKey: item.moduleKey,
            group: group.label || section.label,
          });
        }
      }
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledModules, permissions]);

  const collapsedNavItems = useMemo(
    () =>
      MAIN_PRIMARY_SECTIONS.flatMap((section) =>
        visibleGroupsForSection(section, canShowNavItem).flatMap((group) =>
          group.items.map((item) => ({
            ...item,
            level: group.nested ? ("nested" as const) : ("subfield" as const),
          }))
        )
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabledModules, permissions]
  );

  const renderPrimaryNavItem = (
    item: NavItem,
    level: "subfield" | "nested",
    iconOnly: boolean
  ) => {
    const active = isNavItemActive(pathname, item.to);
    const count = badgeCount(item.badge, counts);
    const ItemIcon = item.icon;
    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={navLinkEnd(item.to)}
        aria-label={iconOnly ? item.label : undefined}
        data-sidebar-tip={iconOnly ? item.label : undefined}
        data-testid={navTestId(item.label)}
        className={cn(
          "primary-sidebar__nav-item",
          level === "nested"
            ? "primary-sidebar__nav-item--nested"
            : "primary-sidebar__nav-item--subfield",
          active && "primary-sidebar__nav-item--active",
          iconOnly && "primary-sidebar__nav-item--icon-only"
        )}
      >
        <ItemIcon className="primary-sidebar__nav-item-icon" aria-hidden />
        {!iconOnly && (
          <>
            <span className="primary-sidebar__nav-item-label">{item.label}</span>
            {count > 0 && (
              <span className="primary-sidebar__nav-item-badge">{count}</span>
            )}
            <ChevronRight className="primary-sidebar__nav-item-chevron" aria-hidden />
          </>
        )}
        {iconOnly && count > 0 && (
          <span className="primary-sidebar__nav-item-dot" aria-label={`${count} pending`} />
        )}
      </NavLink>
    );
  };

  const renderPrimarySubnav = (groups: NavGroup[], iconOnly = false) => (
    <div
      className={cn(
        "primary-sidebar__subnav",
        iconOnly && "primary-sidebar__subnav--icon-only"
      )}
      data-testid="primary-sidebar-subnav"
    >
      {groups.map((group) =>
        group.nested ? (
          <div key={group.label} className="primary-sidebar__subnav-group">
            {!iconOnly && (
              <p className="primary-sidebar__subnav-group-label">{group.label}</p>
            )}
            <div className="primary-sidebar__subnav-list">
              {group.items.map((item) => renderPrimaryNavItem(item, "nested", iconOnly))}
            </div>
          </div>
        ) : (
          <div key={group.label || "flat"} className="primary-sidebar__subnav-flat">
            {group.items.map((item) => renderPrimaryNavItem(item, "subfield", iconOnly))}
          </div>
        )
      )}
    </div>
  );

  const refreshCounts = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
  };

  const primarySidebarInner = (
    <>
      <div className="primary-sidebar__header">
        <div className="primary-sidebar__header-brand">
          <div
            className={cn("primary-sidebar__logo", sidebarCollapsed && "primary-sidebar__logo--collapsed")}
            role={sidebarCollapsed ? "button" : undefined}
            tabIndex={sidebarCollapsed ? 0 : undefined}
            onClick={sidebarCollapsed ? () => setPrimaryPinned(true) : undefined}
            onKeyDown={
              sidebarCollapsed
                ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setPrimaryPinned(true);
                    }
                  }
                : undefined
            }
            data-sidebar-tip={sidebarCollapsed ? "Expand sidebar" : undefined}
            aria-label={sidebarCollapsed ? "Expand sidebar" : undefined}
          >
            <span className="text-sidebar-foreground shrink-0 primary-sidebar__logo-mark">
              <Logo size={sidebarCollapsed ? 30 : 24} />
            </span>
            {!sidebarCollapsed && (
              <div className="primary-sidebar__logo-label flex flex-col min-w-0 leading-none">
                <span className="font-semibold text-[13px] tracking-tight truncate">Ledgerline</span>
              </div>
            )}
          </div>
          {!sidebarCollapsed && (
            <button
              type="button"
              className="primary-sidebar__pin"
              onClick={() => setPrimaryPinned(false)}
              aria-label="Collapse sidebar"
              data-testid="button-sidebar-collapse"
            >
              <PinOff className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {sidebarCollapsed ? (
        <nav className="primary-sidebar__nav primary-sidebar__nav--collapsed-icons" aria-label="Main navigation">
          <div className="primary-sidebar__collapsed-list">
            {collapsedNavItems.map((item) => renderPrimaryNavItem(item, item.level, true))}
          </div>
        </nav>
      ) : (
        <nav className="primary-sidebar__nav" aria-label="Main sections">
          {MAIN_PRIMARY_SECTIONS.map(({ id, label, icon: Icon, groups }) => (
            <div key={id} className="primary-sidebar__section">
              <button
                type="button"
                className={cn(
                  "primary-sidebar__topic",
                  routeSection === id && "primary-sidebar__topic--active"
                )}
                onClick={() => handleSectionTopicClick(id)}
                aria-current={routeSection === id ? "true" : undefined}
                aria-expanded={expandedSection === id}
                data-testid={`nav-section-${id}`}
              >
                <Icon className="primary-sidebar__topic-icon" />
                <span className="primary-sidebar__topic-label truncate">{label}</span>
                <ChevronRight
                  className={cn(
                    "primary-sidebar__topic-chevron",
                    expandedSection === id && "primary-sidebar__topic-chevron--open"
                  )}
                  aria-hidden
                />
              </button>
              {shouldShowSectionSubnav(id) &&
                renderPrimarySubnav(
                  visibleGroupsForSection({ id, label, icon: Icon, groups }, canShowNavItem),
                  false
                )}
            </div>
          ))}
        </nav>
      )}

      <div className="primary-sidebar__footer">
        <button
          type="button"
          className={cn(
            "primary-sidebar__topic",
            searchOpen && "primary-sidebar__topic--active"
          )}
          data-testid="button-global-search"
          data-sidebar-tip={sidebarCollapsed ? "Search" : undefined}
          aria-label="Search"
          aria-haspopup="dialog"
          aria-expanded={searchOpen}
          onClick={() => setSearchOpen(true)}
        >
          <Search className="primary-sidebar__topic-icon" />
          {!sidebarCollapsed && <span className="primary-sidebar__topic-label">Search</span>}
        </button>
        <SettingsSidebarMenu
          collapsed={sidebarCollapsed}
          items={settingsMenuItems}
          isActive={routeSection === "settings"}
        />
        <NotificationBell collapsed={sidebarCollapsed} />
        <ProfileSidebarMenu collapsed={sidebarCollapsed} />
      </div>
    </>
  );

  return (
    <OnboardingChecklistProvider accessToken={accessToken}>
    <div
      className={cn(
        "app-shell app-shell--basic-sidebar grid-cols-1",
        sidebarCollapsed && "app-shell--primary-collapsed"
      )}
    >
      <aside
        className="primary-sidebar"
        data-testid="primary-sidebar"
        onPointerOver={sidebarCollapsed ? onSidebarTipIntent : undefined}
        onFocusCapture={sidebarCollapsed ? onSidebarTipIntent : undefined}
      >
        {primarySidebarInner}
      </aside>

      <GlobalSearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        navItems={searchableNavItems}
      />

      <div className="app-shell__cards app-shell__cards--single">
      {/* Main workspace */}
      <div className="app-workspace">
        {user?.is_support_session && (
          <div
            className="shrink-0 border-b ds-warning-panel border px-4 md:px-6 py-2 text-sm ds-warning-text"
            data-testid="banner-support-mode"
          >
            Platform support mode — viewing <strong>{user.tenant_name}</strong>. Actions are
            audited.
          </div>
        )}

        <main className="app-workspace__main">
          <div className="app-workspace__scroll">
            <Outlet key={user?.tenant_id ?? "anon"} context={{ refreshCounts }} />
          </div>
        </main>

        <footer className="app-workspace__footer flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-medium text-foreground/70 shrink-0">Ledgerline v4</span>
          {user?.email && !user.is_support_session && (
            <span className="hidden sm:inline truncate max-w-[10rem] md:max-w-none">
              {user.email}
            </span>
          )}
          {TRUST.map((t) => (
            <span key={t} className="hidden lg:inline">
              {t}
            </span>
          ))}
          <span className="ml-auto hidden sm:inline">© 2026 Ledgerline · Sandbox environment</span>
          <span className="ml-auto sm:hidden">© 2026</span>
        </footer>

        <nav className="app-mobile-nav" aria-label="Mobile navigation">
          {MOBILE_NAV.filter(canShowNavItem).map(({ to, label, icon: Icon }) => {
            const active = isNavItemActive(pathname, to);
            return (
              <NavLink
                key={to}
                to={to}
                end={navLinkEnd(to)}
                className={cn(
                  "app-mobile-nav__link",
                  active && "app-mobile-nav__link--active"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            );
          })}
        </nav>

        <div className="app-workspace__portal" data-app-workspace-portal />
      </div>
      </div>
      <OnboardingChecklistWidget />
    </div>
    </OnboardingChecklistProvider>
  );
}