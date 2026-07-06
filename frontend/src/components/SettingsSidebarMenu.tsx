import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
} from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronRight, Settings, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

const MENU_WIDTH = 280;
const MENU_GAP = 8;

export type SettingsNavItem = {
  to: string;
  label: string;
  icon?: LucideIcon | ComponentType<{ className?: string }>;
};

type SettingsSidebarMenuProps = {
  collapsed?: boolean;
  items: SettingsNavItem[];
  isActive?: boolean;
};

function pathMatchesItem(pathname: string, to: string) {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}

function isItemActive(pathname: string, to: string, allPaths: string[]): boolean {
  if (!pathMatchesItem(pathname, to)) return false;
  return !allPaths.some(
    (p) => p !== to && p.length > to.length && pathMatchesItem(pathname, p)
  );
}

export function SettingsSidebarMenu({
  collapsed = false,
  items,
  isActive = false,
}: SettingsSidebarMenuProps) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState({ top: 0, left: 0 });

  const allPaths = items.map((item) => item.to);

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const menuHeight = menuRef.current?.offsetHeight ?? 280;
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
  }, [open, updatePosition, items.length]);

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

  const handleTriggerClick = () => {
    setOpen((v) => !v);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={cn(
          "primary-sidebar__topic",
          (isActive || open) && "primary-sidebar__topic--active",
          open && "primary-sidebar__topic--open"
        )}
        data-testid="nav-section-settings"
        aria-label="Settings"
        aria-haspopup="menu"
        aria-expanded={open}
        data-sidebar-tip={collapsed ? "Settings" : undefined}
        onClick={handleTriggerClick}
      >
        <Settings className="primary-sidebar__topic-icon" />
        {!collapsed && <span className="primary-sidebar__topic-label">Settings</span>}
        {!collapsed && (
          <ChevronRight
            className={cn(
              "primary-sidebar__topic-chevron",
              open && "primary-sidebar__topic-chevron--open"
            )}
            aria-hidden
          />
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
              data-testid="menu-settings"
              style={{ top: menuStyle.top, left: menuStyle.left, width: MENU_WIDTH }}
            >
              <div className="profile-menu__header">
                <span className="profile-menu__avatar">
                  <Settings className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <div className="profile-menu__name">Settings</div>
                  <div className="profile-menu__email">Integrations, billing & preferences</div>
                </div>
              </div>

              <div className="profile-menu__section">
                {items.map((item) => {
                  const active = isItemActive(pathname, item.to, allPaths);
                  const ItemIcon = item.icon;
                  return (
                    <button
                      key={item.to}
                      type="button"
                      role="menuitem"
                      className={cn("profile-menu__link", active && "profile-menu__link--active")}
                      data-testid={`settings-menu-${item.label.toLowerCase().replace(/\s+|&/g, "-")}`}
                      onClick={() => {
                        setOpen(false);
                        navigate(item.to);
                      }}
                    >
                      <span className="profile-menu__link-main">
                        {ItemIcon ? (
                          <ItemIcon className="profile-menu__link-icon" aria-hidden />
                        ) : null}
                        <span>{item.label}</span>
                      </span>
                      <ChevronRight className="profile-menu__row-chevron" />
                    </button>
                  );
                })}
              </div>
            </div>
          </>,
          document.body
        )}
    </>
  );
}
