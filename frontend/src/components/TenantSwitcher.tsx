import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Check, ChevronDown, Shield } from "lucide-react";
import { AddOrganisationDialog } from "@/components/AddOrganisationDialog";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/context/AuthContext";
import { fetchMyMemberships, type TenantAccountSummary } from "@/lib/authApi";
import { getAccessToken, loadMembershipsFromSession } from "@/lib/authSession";
import { cn } from "@/lib/cn";

type TenantSwitcherProps = {
  variant: "header" | "sidebar";
  showManageActions?: boolean;
  isCollapsed?: boolean;
};

function formatRole(role: string) {
  return role.replace(/_/g, " ");
}

export function TenantSwitcher({
  variant,
  showManageActions = false,
  isCollapsed = false,
}: TenantSwitcherProps) {
  const navigate = useNavigate();
  const { user, switchTenant } = useAuth();
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [memberships, setMemberships] = useState<TenantAccountSummary[]>(() =>
    loadMembershipsFromSession()
  );
  const [switchingId, setSwitchingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshMemberships = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    try {
      const rows = await fetchMyMemberships(token);
      setMemberships(rows);
      sessionStorage.setItem("ledgerline_memberships", JSON.stringify(rows));
    } catch {
      // Silent — switcher must not block the shell.
    }
  }, []);

  useEffect(() => {
    if (memberships.length === 0) {
      void refreshMemberships();
    }
  }, [memberships.length, refreshMemberships]);

  const currentTenantId = user?.tenant_id;
  const current = useMemo(
    () => memberships.find((m) => m.tenant_id === currentTenantId),
    [memberships, currentTenantId]
  );

  if (memberships.length < 2) {
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

  const triggerClass =
    variant === "header"
      ? "flex items-center gap-2 h-9 max-w-[11rem] px-3 rounded-full border border-border bg-card text-sm hover-elevate shrink-0"
      : cn(
          "flex items-center gap-2 rounded-md border border-sidebar-border bg-sidebar-accent/40 text-sidebar-foreground text-sm hover:bg-sidebar-accent transition-colors",
          isCollapsed ? "h-9 w-9 justify-center p-0" : "w-full px-3 py-2"
        );

  const menuPosition =
    variant === "header"
      ? "absolute right-0 top-full mt-2 w-72"
      : isCollapsed
        ? "absolute left-full ml-2 bottom-0 w-72"
        : "absolute left-0 bottom-full mb-2 w-full min-w-[16rem]";

  const visibilityClass = variant === "header" ? "hidden md:block" : "block md:hidden";

  return (
    <>
      <div className={cn("relative", visibilityClass)}>
        <button
          type="button"
          data-testid="button-tenant-switcher"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Switch organization"
          onClick={() => setOpen((v) => !v)}
          className={triggerClass}
        >
          {current?.is_platform ? (
            <Shield className="h-4 w-4 text-amber-500 shrink-0" />
          ) : (
            <Building2 className="h-4 w-4 text-primary shrink-0" />
          )}
          {!(variant === "sidebar" && isCollapsed) && (
            <>
              <span className="truncate font-medium flex-1 text-left">{displayName}</span>
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            </>
          )}
        </button>

        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div
              role="listbox"
              className={cn(
                "z-50 rounded-md border border-border bg-popover shadow-lg text-sm overflow-hidden",
                menuPosition
              )}
              data-testid="menu-tenant-switcher"
            >
              {error && (
                <p className="px-3 py-2 text-xs text-destructive bg-destructive/10 border-b border-border">
                  {error}
                </p>
              )}
              <p className="px-3 pt-3 pb-2 text-sm font-semibold">Switch organization</p>
              <ul className="px-1 pb-1 max-h-64 overflow-y-auto">
                {memberships.map((m) => {
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
                          "w-full flex items-start gap-2 px-2 py-2 rounded-sm text-left transition-colors hover:bg-accent disabled:opacity-60",
                          busy && "opacity-50",
                          selected && "bg-accent/40"
                        )}
                      >
                        <span className="mt-0.5 shrink-0">
                          {m.is_platform ? (
                            <Shield className="h-4 w-4 text-amber-500" />
                          ) : (
                            <Building2 className="h-4 w-4 text-primary" />
                          )}
                        </span>
                        <span className="flex-1 min-w-0">
                          <span className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-medium truncate">{m.tenant_name}</span>
                            {m.is_platform && (
                              <Badge variant="outline" className="text-[10px] px-1 py-0">
                                Platform
                              </Badge>
                            )}
                          </span>
                          <span className="block text-xs text-muted-foreground capitalize">
                            {formatRole(m.role)}
                          </span>
                        </span>
                        {busy ? (
                          <span className="text-xs text-muted-foreground shrink-0">…</span>
                        ) : selected ? (
                          <Check className="h-4 w-4 text-[hsl(var(--chart-1))] shrink-0 mt-0.5" />
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {showManageActions && (
                <>
                  <div className="h-px bg-border mx-2" />
                  <div className="p-1">
                    <button
                      type="button"
                      className="w-full text-left px-2 py-2 rounded-sm hover:bg-accent text-sm"
                      onClick={() => {
                        setOpen(false);
                        setAddOpen(true);
                      }}
                    >
                      Add organisation
                    </button>
                    <button
                      type="button"
                      className="w-full text-left px-2 py-2 rounded-sm hover:bg-accent text-sm"
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
          </>
        )}
      </div>

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
