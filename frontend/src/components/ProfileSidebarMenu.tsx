import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Building2, Check, ChevronRight, LogOut, Shield } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import {
  themePreferenceLabel,
  useTheme,
  type ThemePreference,
} from "@/context/ThemeContext";
import { fetchMyMemberships, type TenantAccountSummary } from "@/lib/authApi";
import { getAccessToken, loadMembershipsFromSession, persistMemberships } from "@/lib/authSession";
import { SETTINGS_TABS } from "@/lib/settingsTabs";
import { SUPER_ADMIN_ROLE } from "@/lib/roles";
import { formatTenantRole } from "@/lib/tenantRoles";
import { cn } from "@/lib/cn";

const MENU_WIDTH = 280;
const SUBMENU_WIDTH = 200;
const MENU_GAP = 8;

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function switchableMemberships(rows: TenantAccountSummary[]): TenantAccountSummary[] {
  return rows.filter((m) => !m.is_platform || m.role === SUPER_ADMIN_ROLE);
}

type ProfileSidebarMenuProps = {
  collapsed?: boolean;
  /** Compact trigger for mobile header */
  variant?: "sidebar" | "header";
};

export function ProfileSidebarMenu({
  collapsed = false,
  variant = "sidebar",
}: ProfileSidebarMenuProps) {
  const navigate = useNavigate();
  const { user, logout, switchTenant } = useAuth();
  const { themePreference, theme, setThemePreference } = useTheme();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState({ top: 0, left: 0 });
  const [memberships, setMemberships] = useState<TenantAccountSummary[]>(() =>
    loadMembershipsFromSession()
  );
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const refreshMemberships = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    try {
      const rows = await fetchMyMemberships(token);
      setMemberships(rows);
      persistMemberships(rows);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    if (memberships.length === 0) void refreshMemberships();
  }, [memberships.length, refreshMemberships]);

  const visibleMemberships = useMemo(
    () => switchableMemberships(memberships),
    [memberships]
  );
  const current = useMemo(
    () => visibleMemberships.find((m) => m.tenant_id === user?.tenant_id),
    [visibleMemberships, user?.tenant_id]
  );
  const tenantName = current?.tenant_name ?? user?.tenant_name ?? "Workspace";

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const menuHeight = menuRef.current?.offsetHeight ?? 420;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let left = rect.right + MENU_GAP;
    let top = rect.bottom - menuHeight;

    if (left + MENU_WIDTH > vw - MENU_GAP) {
      left = Math.max(MENU_GAP, rect.left - MENU_WIDTH - MENU_GAP);
    }
    top = Math.max(MENU_GAP, Math.min(top, vh - menuHeight - MENU_GAP));

    setMenuStyle({ top, left });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition, visibleMemberships.length]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const handleSwitchTenant = async (tenantId: string) => {
    if (!tenantId || tenantId === user?.tenant_id) return;
    setSwitchingId(tenantId);
    setSwitchError(null);
    try {
      await switchTenant(tenantId);
      setOpen(false);
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : "Could not switch workspace.");
      setSwitchingId(null);
    }
  };

  const themeLabel = themePreferenceLabel(themePreference, theme);

  const themeOptions: { id: ThemePreference; label: string }[] = [
    { id: "light", label: "Light" },
    { id: "dark", label: "Dark" },
    { id: "system", label: "Match system" },
  ];

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={cn(
          variant === "sidebar" ? "primary-sidebar__profile" : "profile-menu-trigger--header",
          open && variant === "sidebar" && "primary-sidebar__profile--open",
          open && variant === "header" && "profile-menu-trigger--header-open"
        )}
        data-testid="button-profile-menu"
        aria-label="Profile"
        aria-haspopup="menu"
        aria-expanded={open}
        data-sidebar-tip={variant === "sidebar" && collapsed ? "Profile" : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className={
            variant === "sidebar"
              ? "primary-sidebar__profile-avatar"
              : "profile-menu-trigger--header-avatar"
          }
        >
          {user ? initials(user.full_name) : "?"}
          <span
            className={
              variant === "sidebar"
                ? "primary-sidebar__profile-status"
                : "profile-menu-trigger--header-status"
            }
            aria-hidden
          />
        </span>
        {variant === "sidebar" && !collapsed && (
          <span className="primary-sidebar__profile-label truncate">Profile</span>
        )}
      </button>

      {open &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[240]" aria-hidden onClick={() => setOpen(false)} />
            <div
              ref={menuRef}
              role="menu"
              className="profile-menu"
              data-testid="menu-profile"
              style={{ top: menuStyle.top, left: menuStyle.left, width: MENU_WIDTH }}
            >
              <div className="profile-menu__header">
                <span className="profile-menu__avatar">
                  {user ? initials(user.full_name) : "?"}
                  <span className="profile-menu__avatar-status" aria-hidden />
                </span>
                <div className="min-w-0">
                  <div className="profile-menu__name truncate">
                    {user?.full_name ?? "User"}
                  </div>
                  {user?.email && (
                    <div className="profile-menu__email truncate">{user.email}</div>
                  )}
                </div>
              </div>

              <div className="profile-menu__section">
                <div className="profile-menu__row profile-menu__row--flyout">
                  <div className="profile-menu__row-main">
                    <span className="profile-menu__row-label">Theme</span>
                    <span className="profile-menu__row-value">{themeLabel}</span>
                  </div>
                  <ChevronRight className="profile-menu__row-chevron" />
                  <div
                    className="profile-menu__flyout"
                    style={{ width: SUBMENU_WIDTH }}
                    role="menu"
                  >
                    {themeOptions.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          role="menuitemradio"
                          aria-checked={themePreference === opt.id}
                          className={cn(
                            "profile-menu__flyout-item",
                            themePreference === opt.id && "profile-menu__flyout-item--theme-selected"
                          )}
                          onClick={() => setThemePreference(opt.id)}
                        >
                          <span>{opt.label}</span>
                          {themePreference === opt.id && (
                            <Check className="dropdown-accent h-4 w-4" />
                          )}
                        </button>
                      ))}
                  </div>
                </div>

                <div className="profile-menu__row profile-menu__row--flyout">
                  <div className="profile-menu__row-main">
                    <span className="profile-menu__row-label">Workspace</span>
                    <span className="profile-menu__row-value truncate">{tenantName}</span>
                  </div>
                  <ChevronRight className="profile-menu__row-chevron" />
                  <div
                    className="profile-menu__flyout profile-menu__flyout--wide"
                    style={{ width: Math.max(SUBMENU_WIDTH, MENU_WIDTH) }}
                    role="menu"
                  >
                    {switchError && (
                      <p className="px-3 py-2 text-xs text-destructive bg-destructive/10 border-b border-border">
                        {switchError}
                      </p>
                    )}
                    {visibleMemberships.length === 0 ? (
                      <p className="px-3 py-2 text-xs text-muted-foreground">
                        {tenantName}
                      </p>
                    ) : (
                      visibleMemberships.map((m) => {
                        const selected = m.tenant_id === user?.tenant_id;
                        const busy = switchingId === m.tenant_id;
                        return (
                          <button
                            key={m.tenant_id}
                            type="button"
                            role="menuitem"
                            disabled={selected || busy}
                            className="profile-menu__flyout-item profile-menu__flyout-item--tenant"
                            onClick={() => void handleSwitchTenant(m.tenant_id)}
                          >
                            <span className="shrink-0">
                              {m.is_platform ? (
                                <Shield className="h-4 w-4 dropdown-accent" />
                              ) : (
                                <Building2 className="h-4 w-4 dropdown-accent" />
                              )}
                            </span>
                            <span className="flex-1 min-w-0 text-left">
                              <span className="block font-medium truncate">{m.tenant_name}</span>
                              <span className="block text-xs text-muted-foreground capitalize truncate">
                                {formatTenantRole(m.role)}
                              </span>
                            </span>
                            {busy ? (
                              <span className="text-xs text-muted-foreground">…</span>
                            ) : selected ? (
                              <Check className="dropdown-accent h-4 w-4" />
                            ) : null}
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>

              <div className="profile-menu__divider" />

              <div className="profile-menu__section">
                <p className="profile-menu__section-title">Settings</p>
                {SETTINGS_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="menuitem"
                    className="profile-menu__link"
                    data-testid={`profile-menu-${tab.id}`}
                    onClick={() => {
                      setOpen(false);
                      navigate(`/settings?tab=${tab.id}`);
                    }}
                  >
                    <span>{tab.label}</span>
                    <ChevronRight className="profile-menu__row-chevron" />
                  </button>
                ))}
              </div>

              <div className="profile-menu__divider" />

              <button
                type="button"
                role="menuitem"
                className="profile-menu__logout"
                data-testid="button-profile-logout"
                onClick={() => {
                  setOpen(false);
                  logout();
                  navigate("/login");
                }}
              >
                <LogOut className="h-4 w-4 shrink-0" />
                Log out
              </button>
            </div>
          </>,
          document.body
        )}
    </>
  );
}
