import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useMemo, useRef, useState, type FocusEvent, type PointerEvent } from "react";
import {
  ArrowLeftRight,
  BarChart3,
  ChevronRight,
  ClipboardCheck,
  Coins,
  CreditCard,
  Link2,
  Pin,
  PinOff,
  Plug,
  Settings,
  Upload,
  Users,
  Vault,
  Wallet,
} from "lucide-react";
import { GlobalSearchBar } from "@/components/GlobalSearchBar";
import { DashboardIcon } from "@/components/icons/DashboardIcon";
import { Logo } from "@/components/Logo";
import { NotificationBell } from "@/components/NotificationBell";
import { ProfileSidebarMenu } from "@/components/ProfileSidebarMenu";
import { SettingsSidebarMenu } from "@/components/SettingsSidebarMenu";
import { useAuth } from "@/context/AuthContext";
import { useNavBadges } from "@/hooks/useNavBadges";
import { useUnpinnedSidebarHover } from "@/hooks/useUnpinnedSidebarHover";
import { canAccessNavPath, usePermissions } from "@/hooks/usePermissions";
import type { FlatNavItem } from "@/lib/appNavigation";
import { canAccessModulePath } from "@/lib/tenantModules";
import { queryClient, queryKeys } from "@/lib/queryClient";
import {
  OnboardingChecklistProvider,
  OnboardingChecklistWidget,
} from "@/components/onboarding/OnboardingChecklist";
import { getAccessToken } from "@/lib/authSession";
import { cn } from "@/lib/cn";
import { kpiModuleIconClass, type KpiModuleColor } from "@/lib/kpiModuleColors";

const ROUTE_PREFETCH: Record<string, () => Promise<unknown>> = {
  "/": () => import("@/pages/DashboardPage"),
  "/upload": () => import("@/pages/UploadPage"),
  "/creations": () => import("@/pages/CreationsPage"),
  "/approvals": () => import("@/pages/ApprovalsPage"),
  "/vault": () => import("@/pages/VaultPage"),
  "/purchases": () => import("@/pages/PurchaseManagementPage"),
  "/sales": () => import("@/pages/SalesManagementPage"),
  "/team-expenses": () => import("@/pages/TeamExpensesPage"),
  "/expenses": () => import("@/pages/ExpensesManagementPage"),
  "/collections": () => import("@/pages/CollectionsPage"),
  "/payments": () => import("@/pages/PaymentsPage"),
  "/bank-feeds": () => import("@/pages/BankFeedsPage"),
  "/customers": () => import("@/pages/CustomersPage"),
  "/vendors": () => import("@/pages/VendorsPage"),
  "/ledger-link": () => import("@/pages/LedgerLinkPage"),
  "/reconciliation": () => import("@/pages/ReconciliationPage"),
  "/matrix": () => import("@/pages/MatrixPage"),
  "/reports": () => import("@/pages/ReportsPage"),
  "/rules": () => import("@/pages/RulesPage"),
  "/integrations": () => import("@/pages/IntegrationsPage"),
  "/billing": () => import("@/pages/BillingPage"),
  "/settings": () => import("@/pages/SettingsPage"),
};

function prefetchRoute(path: string): void {
  const load = ROUTE_PREFETCH[path];
  if (load) void load();
}

type SidebarExtraTone = "sky" | "amber" | "indigo";
type SidebarIconTone = KpiModuleColor | SidebarExtraTone | "muted";

function sidebarIconTileClass(tone: SidebarIconTone): string {
  if (tone === "muted") return "sidebar-icon-tile--muted";
  if (tone === "sky" || tone === "amber" || tone === "indigo") {
    return `sidebar-icon-tile--${tone}`;
  }
  return kpiModuleIconClass(tone);
}

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  iconTone: SidebarIconTone;
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

function SidebarIconTile({
  tone,
  children,
}: {
  tone: SidebarIconTone;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "sidebar-icon-tile",
        sidebarIconTileClass(tone)
      )}
      aria-hidden
    >
      {children}
    </span>
  );
}

const DASHBOARD_ITEM: NavItem = {
  to: "/",
  label: "Dashboard",
  icon: DashboardIcon,
  iconTone: "violet",
};

const UPLOAD_ITEM: NavItem = {
  to: "/upload",
  label: "Upload",
  icon: Upload,
  badge: "upload",
  iconTone: "sky",
};

const APPROVALS_ITEM: NavItem = {
  to: "/approvals",
  label: "Approvals",
  icon: ClipboardCheck,
  badge: "approvals",
  iconTone: "rust",
};

const CONTACTS_ITEM: NavItem = {
  to: "/creations",
  label: "Contacts",
  icon: Users,
  iconTone: "rose",
};

const LEDGER_SYNC_ITEM: NavItem = {
  to: "/ledger-link",
  label: "Ledger Sync",
  icon: Link2,
  moduleKey: "ledger_link",
  iconTone: "indigo",
};

const VAULT_ITEM: NavItem = {
  to: "/vault",
  label: "Vault",
  icon: Vault,
  moduleKey: "vault",
  iconTone: "violet",
};

const REPORTS_ITEM: NavItem = {
  to: "/reports",
  label: "Reports",
  icon: BarChart3,
  moduleKey: "reports",
  iconTone: "indigo",
};

const TOP_LEVEL_LEADING: NavItem[] = [DASHBOARD_ITEM, UPLOAD_ITEM, APPROVALS_ITEM];
const TOP_LEVEL_AFTER_CASHFLOW: NavItem[] = [LEDGER_SYNC_ITEM, VAULT_ITEM, REPORTS_ITEM];
const TOP_LEVEL_TRAILING: NavItem[] = [CONTACTS_ITEM];
const TOP_LEVEL_ITEMS: NavItem[] = [
  ...TOP_LEVEL_LEADING,
  ...TOP_LEVEL_AFTER_CASHFLOW,
  ...TOP_LEVEL_TRAILING,
];

const CASHFLOW_GROUPS: NavGroup[] = [
  {
    label: "",
    nested: false,
    items: [
      {
        to: "/payments",
        label: "Payments",
        icon: Wallet,
        badge: "payments",
        moduleKey: "payments",
        iconTone: "rust",
      },
      {
        to: "/collections",
        label: "Collections",
        icon: Coins,
        badge: "collections",
        moduleKey: "sales",
        iconTone: "sky",
      },
    ],
  },
];

const SETTINGS_GROUPS: NavGroup[] = [
  {
    label: "",
    nested: false,
    items: [
      { to: "/integrations", label: "Integrations", icon: Plug, iconTone: "blue" },
      { to: "/billing", label: "Billing & Credits", icon: CreditCard, iconTone: "amber" },
      { to: "/settings", label: "Organisation", icon: Settings, iconTone: "muted" },
    ],
  },
];

type PrimarySection = {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  iconTone: SidebarIconTone;
  groups: NavGroup[];
};

const CASHFLOW_SECTION: PrimarySection = {
  id: "cashflow",
  label: "Cashflow",
  icon: ArrowLeftRight,
  groups: CASHFLOW_GROUPS,
  iconTone: "sky",
};

const MAIN_PRIMARY_SECTIONS: PrimarySection[] = [CASHFLOW_SECTION];

const SETTINGS_SECTION: PrimarySection = {
  id: "settings",
  label: "Settings",
  icon: Settings,
  groups: SETTINGS_GROUPS,
  iconTone: "muted",
};

const ALL_SECTIONS: PrimarySection[] = [...MAIN_PRIMARY_SECTIONS, SETTINGS_SECTION];

const MOBILE_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: DashboardIcon, iconTone: "violet" },
  { to: "/upload", label: "Upload", icon: Upload, badge: "upload", iconTone: "sky" },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck, badge: "approvals", iconTone: "rust" },
  { to: "/creations", label: "Contacts", icon: Users, iconTone: "rose" },
  { to: "/settings", label: "Settings", icon: Settings, iconTone: "muted" },
];

const SIDEBAR_PIN_STORAGE_KEY = "ledgerline_sidebar_pinned";

function navTestId(label: string) {
  return `nav-${label.toLowerCase().replace(/\s+|&/g, "-")}`;
}

function pathMatchesItem(pathname: string, to: string, search = "") {
  if (to.includes("?")) {
    const [path, queryPart] = to.split("?", 2);
    if (pathname !== path) return false;
    const expected = new URLSearchParams(queryPart);
    const actual = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    for (const [key, value] of expected.entries()) {
      if (actual.get(key) !== value) return false;
    }
    return true;
  }
  if (to === "/") return pathname === "/";
  if (pathname !== to && !pathname.startsWith(`${to}/`)) return false;
  return true;
}

function sectionForPath(pathname: string, search = ""): string {
  if (pathname === "/") return "";
  if (TOP_LEVEL_ITEMS.some((item) => pathMatchesItem(pathname, item.to, search))) return "";
  let bestSection = "";
  let bestPathLen = -1;
  for (const section of ALL_SECTIONS) {
    for (const group of section.groups) {
      for (const item of group.items) {
        if (pathMatchesItem(pathname, item.to, search) && item.to.length > bestPathLen) {
          bestSection = section.id;
          bestPathLen = item.to.length;
        }
      }
    }
  }
  return bestSection;
}

function isNavItemActive(pathname: string, to: string, search = ""): boolean {
  if (!pathMatchesItem(pathname, to, search)) return false;
  const allItems = [
    ...TOP_LEVEL_ITEMS,
    ...ALL_SECTIONS.flatMap((section) => section.groups.flatMap((group) => group.items)),
  ];
  for (const item of allItems) {
    if (
      item.to !== to &&
      item.to.length > to.length &&
      pathMatchesItem(pathname, item.to, search)
    ) {
      return false;
    }
  }
  return true;
}

function navLinkEnd(to: string): boolean {
  if (to === "/") return true;
  const allItems = [
    ...TOP_LEVEL_ITEMS,
    ...ALL_SECTIONS.flatMap((section) => section.groups.flatMap((group) => group.items)),
  ];
  for (const item of allItems) {
    if (item.to !== to && item.to.startsWith(`${to}/`)) return true;
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
  const { pathname, search } = useLocation();
  const { user } = useAuth();
  const { data: badges } = useNavBadges();
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
    collections: badges?.collections_queue_count ?? 0,
  };
  const [expandedSection, setExpandedSection] = useState<string | null>(() =>
    sectionForPath(pathname, search)
  );
  const [sidebarPinned, setSidebarPinned] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_PIN_STORAGE_KEY) === "true";
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
  const prevPathname = useRef(pathname);
  const prevSearch = useRef(search);
  const accessToken = getAccessToken();

  const routeSection = sectionForPath(pathname, search);

  useEffect(() => {
    const section = sectionForPath(pathname, search);
    if (prevPathname.current !== pathname || search !== prevSearch.current) {
      setExpandedSection(section);
    }
    prevPathname.current = pathname;
    prevSearch.current = search;
  }, [pathname, search]);

  useEffect(() => {
    if (sidebarHovered || sidebarPinned) {
      setExpandedSection(routeSection);
    }
  }, [sidebarHovered, sidebarPinned, routeSection]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_PIN_STORAGE_KEY, String(sidebarPinned));
    } catch {
      /* ignore */
    }
  }, [sidebarPinned]);

  const handleSectionTopicClick = (id: string) => {
    setExpandedSection((prev) => (prev === id ? null : id));
  };

  const shouldShowSectionSubnav = (sectionId: string) => expandedSection === sectionId;

  const visibleSettingsGroups = useMemo(
    () => visibleGroupsForSection(SETTINGS_SECTION, canShowNavItem),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabledModules, permissions]
  );

  const visibleCashflowSection = useMemo(() => {
    const groups = visibleGroupsForSection(CASHFLOW_SECTION, canShowNavItem);
    return groups.length > 0 ? CASHFLOW_SECTION : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledModules, permissions]);

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
    for (const item of TOP_LEVEL_ITEMS) {
      if (!canShowNavItem(item)) continue;
      items.push({
        to: item.to,
        label: item.label,
        icon: item.icon as FlatNavItem["icon"],
        badge: item.badge,
        moduleKey: item.moduleKey,
        group: item.label,
      });
    }
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

  const renderPrimaryNavItem = (
    item: NavItem,
    level: "subfield" | "nested",
    iconOnly: boolean
  ) => {
    const active = isNavItemActive(pathname, item.to, search);
    const count = badgeCount(item.badge, counts);
    const ItemIcon = item.icon;
    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={navLinkEnd(item.to)}
        onPointerEnter={() => prefetchRoute(item.to)}
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
        <SidebarIconTile tone={item.iconTone}>
          <ItemIcon className="primary-sidebar__nav-item-icon" aria-hidden />
        </SidebarIconTile>
        {!iconOnly && (
          <>
            <span className="primary-sidebar__nav-item-label">{item.label}</span>
            {count > 0 && (
              <span className="primary-sidebar__nav-item-badge">{count}</span>
            )}
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

  const renderTopLevelNavItem = (item: NavItem, iconOnly: boolean) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === "/" ? true : navLinkEnd(item.to)}
      onPointerEnter={() => prefetchRoute(item.to)}
      aria-label={iconOnly ? item.label : undefined}
      data-sidebar-tip={iconOnly ? item.label : undefined}
      data-testid={navTestId(item.label)}
      className={cn(
        "primary-sidebar__topic",
        item.to === "/" && "primary-sidebar__topic--dashboard",
        iconOnly && "primary-sidebar__topic--icon-only",
        isNavItemActive(pathname, item.to) && "primary-sidebar__topic--active"
      )}
    >
      <SidebarIconTile tone={item.iconTone}>
        <item.icon className="primary-sidebar__topic-icon" aria-hidden />
      </SidebarIconTile>
      {!iconOnly && (
        <>
          <span className="primary-sidebar__topic-label">{item.label}</span>
          {badgeCount(item.badge, counts) > 0 ? (
            <span className="primary-sidebar__nav-item-badge tnum">
              {badgeCount(item.badge, counts)}
            </span>
          ) : null}
        </>
      )}
      {iconOnly && badgeCount(item.badge, counts) > 0 ? (
        <span
          className="primary-sidebar__nav-item-dot"
          aria-label={`${badgeCount(item.badge, counts)} pending`}
        />
      ) : null}
    </NavLink>
  );

  const renderPrimarySection = (section: PrimarySection, iconOnly: boolean) => {
    const { id, label, icon: Icon, iconTone } = section;
    return (
      <div key={id} className="primary-sidebar__section">
        <button
          type="button"
          className={cn(
            "primary-sidebar__topic",
            iconOnly && "primary-sidebar__topic--icon-only",
            routeSection === id && "primary-sidebar__topic--active"
          )}
          onClick={iconOnly ? undefined : () => handleSectionTopicClick(id)}
          aria-label={iconOnly ? label : undefined}
          aria-current={!iconOnly && routeSection === id ? "true" : undefined}
          aria-expanded={!iconOnly ? expandedSection === id : undefined}
          data-sidebar-tip={iconOnly ? label : undefined}
          data-testid={`nav-section-${id}`}
        >
          <SidebarIconTile tone={iconTone}>
            <Icon className="primary-sidebar__topic-icon" />
          </SidebarIconTile>
          {!iconOnly && (
            <>
              <span className="primary-sidebar__topic-label truncate">{label}</span>
              <ChevronRight
                className={cn(
                  "primary-sidebar__topic-chevron",
                  expandedSection === id && "primary-sidebar__topic-chevron--open"
                )}
                aria-hidden
              />
            </>
          )}
        </button>
        {!iconOnly &&
          shouldShowSectionSubnav(id) &&
          renderPrimarySubnav(visibleGroupsForSection(section, canShowNavItem), false)}
      </div>
    );
  };

  const refreshCounts = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
  };

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
                <span className="font-semibold text-[13px] tracking-tight truncate">Ledgerlink</span>
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

      <nav className="primary-sidebar__nav" aria-label="Main sections">
        {TOP_LEVEL_LEADING.filter(canShowNavItem).map((item) =>
          renderTopLevelNavItem(item, iconOnly)
        )}
        {visibleCashflowSection
          ? renderPrimarySection(visibleCashflowSection, iconOnly)
          : null}
        {TOP_LEVEL_AFTER_CASHFLOW.filter(canShowNavItem).map((item) =>
          renderTopLevelNavItem(item, iconOnly)
        )}
        {TOP_LEVEL_TRAILING.filter(canShowNavItem).map((item) =>
          renderTopLevelNavItem(item, iconOnly)
        )}
      </nav>

      <div className="primary-sidebar__footer">
        <SettingsSidebarMenu
          collapsed={iconOnly}
          items={settingsMenuItems}
          isActive={routeSection === "settings"}
        />
        <ProfileSidebarMenu collapsed={iconOnly} />
      </div>
    </>
  );

  return (
    <OnboardingChecklistProvider accessToken={accessToken}>
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

        <header className="app-workspace__header app-workspace__header--search">
          <div className="app-workspace__header-slot" aria-hidden="true" />
          <GlobalSearchBar navItems={searchableNavItems} />
          <div className="app-workspace__header-end">
            <NotificationBell variant="header" />
          </div>
        </header>

        <main className="app-workspace__main">
          <div className="app-workspace__scroll">
            <Outlet key={user?.tenant_id ?? "anon"} context={{ refreshCounts }} />
          </div>
        </main>

        <nav className="app-mobile-nav" aria-label="Mobile navigation">
          {MOBILE_NAV.filter(canShowNavItem).map(({ to, label, icon: Icon }) => {
            const active = isNavItemActive(pathname, to, search);
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