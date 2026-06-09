import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Check, ChevronDown } from "lucide-react";
import { api } from "@/api/client";
import type { Organisation } from "@/api/types";
import { AddOrganisationDialog } from "@/components/AddOrganisationDialog";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/cn";

export function OrgSwitcher() {
  const navigate = useNavigate();
  const { user, switchOrganisation, refreshUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [orgs, setOrgs] = useState<Organisation[]>([]);
  const [loading, setLoading] = useState(true);
  const [switchingId, setSwitchingId] = useState<number | null>(null);

  const loadOrgs = useCallback(() => {
    if (!user) {
      setOrgs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .listOrganisations()
      .then(setOrgs)
      .catch(() => {
        setOrgs([
          {
            id: user.org_id,
            name: user.org_name,
            slug: user.org_slug,
            currency: "AUD",
            is_current: true,
          },
        ]);
      })
      .finally(() => setLoading(false));
  }, [user]);

  useEffect(() => {
    loadOrgs();
  }, [loadOrgs]);

  const active =
    orgs.find((o) => o.id === user?.org_id) ??
    orgs.find((o) => o.is_current) ??
    orgs[0];

  const canSwitch = orgs.length > 1;

  const selectOrg = async (org: Organisation) => {
    if (org.id === user?.org_id) {
      setOpen(false);
      return;
    }
    setSwitchingId(org.id);
    try {
      await switchOrganisation(org.id);
      loadOrgs();
      setOpen(false);
      window.location.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not switch organisation");
    } finally {
      setSwitchingId(null);
    }
  };

  const displayName = active?.name ?? user?.org_name ?? "Organisation";

  return (
    <>
      <div className="relative hidden md:block">
        <button
          type="button"
          data-testid="button-org-switcher"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-card text-sm hover-elevate max-w-[240px]"
        >
          <Building2 className="h-4 w-4 text-primary shrink-0" />
          <span className="truncate font-medium">
            {loading ? "Loading…" : displayName}
          </span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div
              className="absolute left-0 top-full mt-1 z-50 w-72 rounded-md border border-border bg-popover shadow-lg text-sm overflow-hidden"
              data-testid="menu-org-switcher"
            >
              <p className="px-3 pt-3 pb-2 text-sm font-semibold">Organisations</p>
              <ul className="px-1 pb-1">
                {orgs.map((org) => {
                  const selected = org.id === user?.org_id;
                  const busy = switchingId === org.id;
                  return (
                    <li key={org.id}>
                      <button
                        type="button"
                        data-testid={`org-option-${org.id}`}
                        onClick={() => void selectOrg(org)}
                        disabled={busy}
                        className={cn(
                          "w-full flex items-center gap-2 px-2 py-2 rounded-sm text-left transition-colors hover:bg-accent",
                          selected && "bg-accent/40"
                        )}
                      >
                        <span className="flex-1 truncate font-medium">{org.name}</span>
                        <span className="text-xs text-muted-foreground tnum shrink-0">
                          {org.currency}
                        </span>
                        {busy ? (
                          <span className="text-xs text-muted-foreground">…</span>
                        ) : selected ? (
                          <Check className="h-4 w-4 text-[hsl(var(--chart-1))] shrink-0" />
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {canSwitch && (
                <p className="px-3 pb-2 text-xs text-muted-foreground">
                  Select an organisation to switch tenant context.
                </p>
              )}
              <div className="h-px bg-border mx-2" />
              <div className="p-1">
                <button
                  type="button"
                  data-testid="button-add-organisation"
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
                  data-testid="button-manage-organisations"
                  className="w-full text-left px-2 py-2 rounded-sm hover:bg-accent text-sm"
                  onClick={() => {
                    setOpen(false);
                    navigate("/settings?tab=orgs");
                  }}
                >
                  Manage organisations
                </button>
              </div>
            </div>
          </>
        )}
      </div>
      <AddOrganisationDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={() => {
          void refreshUser();
          loadOrgs();
          window.location.reload();
        }}
      />
    </>
  );
}
