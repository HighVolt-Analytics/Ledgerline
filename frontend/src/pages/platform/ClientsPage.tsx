import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { api } from "@/api/client";
import type { PlatformTenantSummary } from "@/api/types";
import { CreateTenantWizard } from "@/components/platform/CreateTenantWizard";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";

function statusVariant(status: string): "default" | "outline" | "destructive" {
  if (status === "active") return "default";
  if (status === "suspended") return "destructive";
  return "outline";
}

export function ClientsPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<PlatformTenantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const loadTenants = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .listPlatformTenants()
      .then(setTenants)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load clients"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadTenants();
  }, [loadTenants]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tenants;
    return tenants.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.slug.toLowerCase().includes(q) ||
        t.lifecycle_status.toLowerCase().includes(q) ||
        String(t.id).includes(q)
    );
  }, [tenants, search]);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Clients"
        subtitle="Manage all client tenants on the platform."
        actions={
          <Button onClick={() => setCreateOpen(true)} data-testid="button-create-tenant">
            <Plus className="h-4 w-4 mr-1.5" />
            New client
          </Button>
        }
      />

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search by name, slug, ID, or status…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading clients…</p>
      ) : filtered.length === 0 ? (
        <Card className="p-8 text-center text-muted-foreground text-sm">
          {tenants.length === 0
            ? "No client tenants yet. Create your first client to get started."
            : "No clients match your search."}
        </Card>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-4 py-3 min-w-[14rem]">Tenant ID</th>
                <th className="text-left font-medium px-4 py-3">Client</th>
                <th className="text-left font-medium px-4 py-3 hidden sm:table-cell">Slug</th>
                <th className="text-left font-medium px-4 py-3">Status</th>
                <th className="text-right font-medium px-4 py-3 hidden md:table-cell">Users</th>
                <th className="text-right font-medium px-4 py-3 hidden md:table-cell">Pending</th>
                <th className="text-right font-medium px-4 py-3 hidden lg:table-cell">Invoices</th>
                <th className="text-right font-medium px-4 py-3 hidden lg:table-cell">Credits</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((tenant) => (
                <tr
                  key={tenant.id}
                  className={cn(
                    "border-t border-border cursor-pointer hover:bg-muted/40 transition-colors",
                    !tenant.is_active && "opacity-60"
                  )}
                  onClick={() => navigate(`/platform/clients/${tenant.id}`)}
                  data-testid={`client-row-${tenant.id}`}
                >
                  <td className="px-4 py-3 text-muted-foreground font-mono text-[11px] max-w-[14rem] truncate" title={tenant.id}>
                    {tenant.id}
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{tenant.name}</div>
                    <div className="text-xs text-muted-foreground sm:hidden">{tenant.slug}</div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground hidden sm:table-cell font-mono text-xs">
                    {tenant.slug}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant={statusVariant(tenant.lifecycle_status)}>
                        {tenant.lifecycle_status}
                      </Badge>
                      {!tenant.is_active && <Badge variant="outline">Disabled</Badge>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right tnum hidden md:table-cell">
                    {tenant.user_count}
                  </td>
                  <td className="px-4 py-3 text-right tnum hidden md:table-cell">
                    {tenant.pending_invite_count}
                  </td>
                  <td className="px-4 py-3 text-right tnum hidden lg:table-cell">
                    {tenant.invoice_count}
                  </td>
                  <td className="px-4 py-3 text-right tnum hidden lg:table-cell">
                    {tenant.credit_balance.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateTenantWizard
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(tenantId) => {
          loadTenants();
          navigate(`/platform/clients/${tenantId}`);
        }}
      />
    </div>
  );
}
