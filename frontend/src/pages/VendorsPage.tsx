import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import {
  API_PORT_HINT,
  captureTenantFetchScope,
  formatTenantLoadError,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";
import { Building2, ClipboardCheck, Pencil, Plus, RefreshCw, Search, Trash2, AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import type { Invoice, TopVendorRow, Vendor } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { VendorFormDialog } from "@/components/VendorFormDialog";
import { AccountBadge } from "@/components/rule-book/AccountBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { usePendingVendors, usePromotePendingVendor } from "@/hooks/useMasterData";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { formatTaxId, money, toNumber } from "@/lib/format";

const VENDORS_POLL_MS = 30_000;
import { fetchAllInvoices } from "@/lib/invoices";

type VendorInvoiceStats = {
  amount: number;
  count: number;
  email: string | null;
  defaultAccount: string;
  netDays: number | null;
};

function normalizeVendorKey(name: string | null | undefined): string {
  return (name ?? "").trim().toLowerCase();
}

function vendorMatchesInvoice(vendor: Vendor, invoiceVendor: string | null): boolean {
  const key = normalizeVendorKey(invoiceVendor);
  if (!key) return false;
  const name = normalizeVendorKey(vendor.vendor_name);
  const slug = vendor.vendor_slug.replace(/-/g, " ");
  return key === name || key.includes(name) || name.includes(key) || key.includes(slug);
}

function inferNetDays(inv: Invoice): number | null {
  if (!inv.invoice_date || !inv.due_date) return null;
  const start = new Date(inv.invoice_date);
  const end = new Date(inv.due_date);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000);
  return days >= 0 ? days : null;
}

function buildInvoiceStats(invoices: Invoice[]): Map<string, VendorInvoiceStats> {
  const map = new Map<string, VendorInvoiceStats>();

  for (const inv of invoices) {
    const key = normalizeVendorKey(inv.vendor);
    if (!key) continue;

    const entry = map.get(key) ?? {
      amount: 0,
      count: 0,
      email: null,
      defaultAccount: "Suspense Account",
      netDays: null,
    };

    entry.amount += toNumber(inv.total);
    entry.count += 1;
    if (inv.email_sender) entry.email = inv.email_sender;
    if (inv.account_name) entry.defaultAccount = inv.account_name;
    const days = inferNetDays(inv);
    if (days != null) entry.netDays = days;

    map.set(key, entry);
  }

  return map;
}

function lookupVendorStats(
  vendor: Vendor,
  statsByVendor: Map<string, VendorInvoiceStats>
): VendorInvoiceStats {
  for (const [key, stats] of statsByVendor) {
    if (vendorMatchesInvoice(vendor, key)) return stats;
  }
  return {
    amount: 0,
    count: 0,
    email: null,
    defaultAccount: "Suspense Account",
    netDays: null,
  };
}

function topVendorsBySpend(invoices: Invoice[], limit = 5): TopVendorRow[] {
  const totals = new Map<string, { amount: number; count: number }>();

  for (const inv of invoices) {
    const name = (inv.vendor ?? "Unknown").trim() || "Unknown";
    const entry = totals.get(name) ?? { amount: 0, count: 0 };
    entry.amount += toNumber(inv.total);
    entry.count += 1;
    totals.set(name, entry);
  }

  return [...totals.entries()]
    .sort((a, b) => b[1].amount - a[1].amount)
    .slice(0, limit)
    .map(([vendor, { amount, count }]) => ({ vendor, amount, invoice_count: count }));
}

function vendorDisplayEmail(vendor: Vendor, stats: VendorInvoiceStats): string {
  if (stats.email) return stats.email;
  const pattern = vendor.sender_pattern.trim();
  if (pattern.startsWith("@")) return `billing${pattern}`;
  if (pattern.includes("@")) return pattern;
  return pattern || "—";
}

function vendorTerms(stats: VendorInvoiceStats): string {
  if (stats.netDays != null) return `Net ${stats.netDays}`;
  return "—";
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 pb-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="tnum font-medium">{value}</span>
    </div>
  );
}

export function VendorsPage() {
  const { user } = useAuth();
  const { data: pendingQueue = [] } = usePendingVendors(Boolean(user));
  const promoteMutation = usePromotePendingVendor();
  const currency = "SGD";
  const [rows, setRows] = useState<Vendor[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editVendor, setEditVendor] = useState<Vendor | null>(null);

  useResetOnTenantChange(() => {
    setRows([]);
    setInvoices([]);
    setLoading(true);
    setError(null);
    setSearch("");
    setFormOpen(false);
    setEditVendor(null);
  });

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    const scope = captureTenantFetchScope();
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const fresh = options?.fresh ?? !options?.silent;
      const [vendors, invoiceRows] = await Promise.all([
        api.listVendors({ fresh }),
        fetchAllInvoices(fresh),
      ]);
      if (!isTenantFetchScopeCurrent(scope)) return;
      setRows(vendors);
      setInvoices(invoiceRows);
    } catch (e) {
      if (!isTenantFetchScopeCurrent(scope)) return;
      if (
        handleTenantScopedLoadFailure(e, {
          retry: () => {
            void load({ silent: true, fresh: true });
          },
        })
      ) {
        return;
      }
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load vendors");
        setRows([]);
        setInvoices([]);
      }
    } finally {
      if (isTenantFetchScopeCurrent(scope) && !options?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, user?.tenant_id]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, VENDORS_POLL_MS);

  const statsByVendor = useMemo(() => buildInvoiceStats(invoices), [invoices]);
  const topVendors = useMemo(() => topVendorsBySpend(invoices, 5), [invoices]);
  const totalSpend = useMemo(
    () => invoices.reduce((sum, inv) => sum + toNumber(inv.total), 0),
    [invoices]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (v) =>
        v.vendor_name.toLowerCase().includes(q) ||
        v.vendor_slug.toLowerCase().includes(q) ||
        (v.abn ?? "").includes(q) ||
        v.sender_pattern.toLowerCase().includes(q)
    );
  }, [rows, search]);

  const activeCount = rows.filter((v) => v.approved).length;
  const onHoldCount = rows.length - activeCount;
  const topMax = toNumber(topVendors[0]?.amount);

  const openAddVendor = () => {
    setEditVendor(null);
    setFormOpen(true);
  };

  const toggleApproved = async (vendor: Vendor) => {
    try {
      await api.updateVendor(vendor.id, { approved: !vendor.approved });
      await load({ silent: true, fresh: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  };

  const saveVendor = async (body: Omit<Vendor, "id" | "created_at">) => {
    if (editVendor) {
      await api.updateVendor(editVendor.id, body);
    } else {
      await api.createVendor(body);
    }
    await load({ fresh: true });
  };

  const deleteVendor = async (vendor: Vendor) => {
    if (!window.confirm(`Delete vendor ${vendor.vendor_name}?`)) return;
    try {
      await api.deleteVendor(vendor.id);
      await load({ fresh: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  if (error && !loading && rows.length === 0) {
    return (
      <>
        <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
          {formatTenantLoadError(error, API_PORT_HINT)}
        </Card>
        <VendorFormDialog
          open={formOpen}
          vendor={editVendor}
          onClose={() => { setFormOpen(false); setEditVendor(null); }}
          onSave={saveVendor}
        />
      </>
    );
  }

  if (loading) {
    return (
      <div>
        <PageHeader
          title="Vendors"
          subtitle="Vendor master with default coding, payment terms and spend."
        />
        <TableSkeleton rows={8} columns={5} />
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <>
        <div>
          <PageHeader
            title="Vendors"
            subtitle="Vendor master with default coding, payment terms and status."
            actions={
              <Button size="sm" onClick={openAddVendor}>
                <Plus className="h-4 w-4 mr-1" />
                Add vendor
              </Button>
            }
          />
          <EmptyState
            title="No vendors yet"
            hint="Add a vendor manually or they will be created as documents are captured."
            action={
              <Button size="sm" onClick={openAddVendor}>
                <Plus className="h-4 w-4 mr-1" />
                Add vendor
              </Button>
            }
          />
        </div>
        <VendorFormDialog
          open={formOpen}
          vendor={editVendor}
          onClose={() => { setFormOpen(false); setEditVendor(null); }}
          onSave={saveVendor}
        />
      </>
    );
  }

  return (
    <div>
      <PageHeader
        title="Vendors"
        subtitle="Vendor master with default coding, payment terms and spend."
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search vendors…"
                className="pl-8 h-9 w-56"
                data-testid="input-vendor-search"
              />
            </div>
            <Button
              size="sm"
              onClick={openAddVendor}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add vendor
            </Button>
            <Button
              variant="surface"
              size="sm"
              onClick={() => load({ fresh: true })}
              disabled={loading}
              aria-label="Refresh vendors"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      {error && (
        <Card className="p-3 mb-4 text-xs text-destructive border-destructive/30 bg-destructive/5">
          {error}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <Card className="p-4 lg:col-span-2">
          <h3 className="text-sm font-semibold mb-3">Top vendors by spend</h3>
          {topVendors.length === 0 ? (
            <p className="text-sm text-muted-foreground">No invoice spend recorded yet.</p>
          ) : (
            <div className="space-y-2.5">
              {topVendors.map((row) => (
                <div key={row.vendor} className="flex items-center gap-3">
                  <span className="text-sm truncate w-40 shrink-0">{row.vendor}</span>
                  <div className="flex-1 h-2.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{
                        width: `${topMax ? (toNumber(row.amount) / topMax) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <span className="tnum text-sm font-medium w-28 text-right shrink-0">
                    {money(row.amount, currency)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-3">Summary</h3>
          <div className="space-y-2 text-sm">
            <SummaryRow label="Active vendors" value={String(activeCount)} />
            <SummaryRow label="On hold" value={String(onHoldCount)} />
            <SummaryRow label="Total vendors" value={String(rows.length)} />
            <SummaryRow label="Spend (loaded)" value={money(totalSpend, currency)} />
          </div>
        </Card>
      </div>

      {pendingQueue.length > 0 && (
        <Card className="p-4 mb-6" data-testid="vendors-pending-queue">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive shrink-0" aria-hidden />
            Pending vendor registration
          </h3>
          <div className="space-y-2">
            {pendingQueue.map((item) => (
              <div
                key={item.id}
                className="vendors-pending-item flex items-center justify-between gap-3 flex-wrap rounded-lg border p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">{item.detectedName}</div>
                  <div className="text-xs text-muted-foreground">
                    Match confidence {item.confidence}% · from pipeline detection
                  </div>
                </div>
                <Button
                  size="sm"
                  disabled={promoteMutation.isPending}
                  onClick={() =>
                    promoteMutation.mutate({
                      pendingId: item.id,
                      body: { name: item.detectedName, status: "Pending registration" },
                    })
                  }
                  data-testid={`vendors-promote-${item.id}`}
                >
                  <ClipboardCheck className="h-4 w-4 mr-1" />
                  Register vendor
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="px-4 py-2 font-medium">Vendor</th>
                <th className="px-3 py-2 font-medium">Tax ID</th>
                <th className="px-3 py-2 font-medium">Default account</th>
                <th className="px-3 py-2 font-medium">Terms</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium text-right">Docs</th>
                <th className="px-4 py-2 font-medium text-right">Spend</th>
                <th className="px-3 py-2 font-medium text-right w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">
                    No vendors match your search.
                  </td>
                </tr>
              ) : (
                filtered.map((vendor) => {
                  const stats = lookupVendorStats(vendor, statsByVendor);
                  const status = vendor.approved ? "Active" : "On hold";
                  return (
                    <tr
                      key={vendor.id}
                      className="row-band border-b border-border/60 last:border-0 hover-elevate"
                      data-testid={`row-vendor-${vendor.vendor_slug}`}
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
                          <div>
                            <div className="font-medium">{vendor.vendor_name}</div>
                            <div className="text-xs text-muted-foreground">
                              {vendorDisplayEmail(vendor, stats)}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 tnum text-muted-foreground">
                        {formatTaxId(vendor.abn)}
                      </td>
                      <td className="px-3 py-2.5">
                        <AccountBadge account={stats.defaultAccount} />
                      </td>
                      <td className="px-3 py-2.5 tnum">{vendorTerms(stats)}</td>
                      <td className="px-3 py-2.5">
                        <button
                          type="button"
                          onClick={() => toggleApproved(vendor)}
                          title="Click to toggle status"
                        >
                          <Badge
                            variant="outline"
                            className={cn(
                              "font-normal cursor-pointer",
                              status === "Active"
                                ? "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]"
                                : "border-[rgb(var(--system-yellow-rgb)/0.35)] text-[var(--system-yellow-text)]"
                            )}
                          >
                            {status}
                          </Badge>
                        </button>
                      </td>
                      <td className="px-3 py-2.5 text-right tnum">{stats.count}</td>
                      <td className="px-4 py-2.5 text-right tnum font-medium">
                        {money(stats.amount, currency)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            aria-label="Edit vendor"
                            onClick={() => { setEditVendor(vendor); setFormOpen(true); }}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive"
                            aria-label="Delete vendor"
                            onClick={() => void deleteVendor(vendor)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <VendorFormDialog
        open={formOpen}
        vendor={editVendor}
        onClose={() => { setFormOpen(false); setEditVendor(null); }}
        onSave={saveVendor}
      />
    </div>
  );
}
