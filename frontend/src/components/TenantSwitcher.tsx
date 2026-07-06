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
import { Building2, Check, ChevronDown, Shield } from "lucide-react";
import { AddOrganisationDialog } from "@/components/AddOrganisationDialog";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { fetchMyMemberships, type TenantAccountSummary } from "@/lib/authApi";
import { getAccessToken, loadMembershipsFromSession, persistMemberships, PROFILE_UPDATED_EVENT } from "@/lib/authSession";
import { cn } from "@/lib/cn";

type TenantSwitcherProps = {
  /** @deprecated styling is responsive; prop is ignored */
  variant?: "header" | "sidebar";
  showManageActions?: boolean;
  /** @deprecated unused */
  isCollapsed?: boolean;
};

const MENU_WIDTH = 288;
const MENU_GAP = 8;

import { formatTenantRole } from "@/lib/tenantRoles";
import { SUPER_ADMIN_ROLE } from "@/lib/roles";

function switchableMemberships(rows: TenantAccountSummary[]): TenantAccountSummary[] {
  return rows.filter((m) => !m.is_platform || m.role === SUPER_ADMIN_ROLE);
}

function computeMenuPosition(rect: DOMRect, menuHeight: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = rect.left;
  const width = Math.max(rect.width, MENU_WIDTH);
  if (left + width > vw - MENU_GAP) {
    left = rect.right - width;
  }
  left = Math.max(MENU_GAP, Math.min(left, vw - width - MENU_GAP));

  const spaceBelow = vh - rect.bottom - MENU_GAP;
  const spaceAbove = rect.top - MENU_GAP;
  let top: number;
  if (spaceBelow >= menuHeight || spaceBelow >= spaceAbove) {
    top = rect.bottom + MENU_GAP;
  } else {
    top = Math.max(MENU_GAP, rect.top - menuHeight - MENU_GAP);
  }

  return { top, left, width };
}

export function TenantSwitcher({
  showManageActions = false,
}: TenantSwitcherProps) {
  const navigate = useNavigate();
  const { user, switchTenant } = useAuth();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [memberships, setMemberships] = useState<TenantAccountSummary[]>(() =>
    loadMembershipsFromSession()
  );
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menuStyle, setMenuStyle] = useState({ top: 0, left: 0, width: MENU_WIDTH });

  const refreshMemberships = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    try {
      const rows = await fetchMyMemberships(token);
      setMemberships(rows);
      persistMemberships(rows);
    } catch {
      // Silent — switcher must not block the shell.
    }
  }, []);

  useEffect(() => {
    if (memberships.length === 0) {
      void refreshMemberships();
    }
  }, [memberships.length, refreshMemberships]);

  useEffect(() => {
    const onProfileUpdated = () => {
      void refreshMemberships();
    };
    window.addEventListener(PROFILE_UPDATED_EVENT, onProfileUpdated);
    return () => window.removeEventListener(PROFILE_UPDATED_EVENT, onProfileUpdated);
  }, [refreshMemberships]);

  const currentTenantId = user?.tenant_id;
  const visibleMemberships = useMemo(
    () => switchableMemberships(memberships),
    [memberships]
  );
  const current = useMemo(
    () => visibleMemberships.find((m) => m.tenant_id === currentTenantId),
    [visibleMemberships, currentTenantId]
  );

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const menuHeight = menuRef.current?.offsetHeight ?? 320;
    setMenuStyle(computeMenuPosition(rect, menuHeight));
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
  }, [open, updatePosition, visibleMemberships.length, showManageActions, error]);

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

  if (visibleMemberships.length < 2) {
    return null;
  }

  const displayName = current?.tenant_name ?? user?.tenant_name ?? "Organisation";

  const handleSwitch = async (tenantId: string) => {
    if (!tenantId || tenantId === currentTenantId) {
      setOpen(false);
      return;
    }
    setSwitchingId(tenantId);
    setError(null);
    try {
      await switchTenant(tenantId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not switch organization.");
      setSwitchingId(null);
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        data-testid="button-tenant-switcher"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch organization"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 h-9 min-w-0 max-w-[10rem] sm:max-w-[12rem] px-3 rounded-full border border-border bg-card text-sm hover-elevate shrink-0"
      >
        {current?.is_platform ? (
          <Shield className="h-4 w-4 ds-warning-icon shrink-0" />
        ) : (
          <Building2 className="h-4 w-4 text-primary shrink-0" />
        )}
        <span className="truncate font-medium flex-1 text-left">{displayName}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground shrink-0 transition-transform duration-150",
            open && "rotate-180"
          )}
        />
      </button>

      {open &&
        createPortal(
          <>
            <div className="fixed inset-0 z-[240]" aria-hidden onClick={() => setOpen(false)} />
            <div
              ref={menuRef}
              role="listbox"
              data-testid="menu-tenant-switcher"
              className="fixed z-[250] rounded-lg border border-border bg-popover shadow-float text-sm overflow-hidden"
              style={{
                top: menuStyle.top,
                left: menuStyle.left,
                width: menuStyle.width,
              }}
            >
              {error && (
                <p className="px-3 py-2 text-xs text-destructive bg-destructive/10 border-b border-border">
                  {error}
                </p>
              )}
              <div className="px-3 pt-3 pb-2 border-b border-border/60">
                <p className="text-sm font-semibold">Switch organization</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {visibleMemberships.length} workspaces available
                </p>
              </div>
              <ul className="p-1 max-h-64 overflow-y-auto">
                {visibleMemberships.map((m) => {
                  const selected = m.tenant_id === currentTenantId;
                  const busy = switchingId === m.tenant_id;
                  return (
                    <li key={m.tenant_id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={selected}
                        disabled={selected || busy}
                        data-testid={`tenant-option-${m.tenant_id}`}
                        onClick={() => void handleSwitch(m.tenant_id)}
                        className={cn(
                          "w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-left transition-colors hover:bg-accent disabled:cursor-default",
                          busy && "opacity-60",
                          selected && "bg-accent/50"
                        )}
                      >
                        <span className="shrink-0">
                          {m.is_platform ? (
                            <Shield className="h-4 w-4 dropdown-accent" />
                          ) : (
                            <Building2 className="h-4 w-4 dropdown-accent" />
                          )}
                        </span>
                        <span className="flex-1 min-w-0">
                          <span className="flex items-center gap-1.5 min-w-0">
                            <span className="font-medium truncate">{m.tenant_name}</span>
                            {m.is_platform && (
                              <Badge variant="outline" className="text-[10px] px-1 py-0 shrink-0">
                                Platform
                              </Badge>
                            )}
                          </span>
                          <span className="block text-xs text-muted-foreground capitalize truncate">
                            {formatTenantRole(m.role)}
                          </span>
                        </span>
                        {busy ? (
                          <span className="text-xs text-muted-foreground shrink-0">…</span>
                        ) : selected ? (
                          <Check className="dropdown-accent h-4 w-4" />
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {showManageActions && (
                <>
                  <div className="h-px bg-border" />
                  <div className="p-1">
                    <button
                      type="button"
                      className="w-full text-left px-2.5 py-2 rounded-md hover:bg-accent text-sm"
                      onClick={() => {
                        setOpen(false);
                        setAddOpen(true);
                      }}
                    >
                      Add organisation
                    </button>
                    <button
                      type="button"
                      className="w-full text-left px-2.5 py-2 rounded-md hover:bg-accent text-sm"
                      onClick={() => {
                        setOpen(false);
                        navigate("/settings?tab=orgs");
                      }}
                    >
                      Manage organisations
                    </button>
                  </div>
                </>
              )}
            </div>
          </>,
          document.body
        )}

      {showManageActions && (
        <AddOrganisationDialog
          open={addOpen}
          onClose={() => setAddOpen(false)}
          onCreated={() => {
            void refreshMemberships();
            window.location.reload();
          }}
        />
      )}
    </>
  );
}

/** @deprecated use TenantSwitcher */
export const OrgSwitcher = TenantSwitcher;
