import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import type { Customer, Invoice } from "@/api/types";
import { CustomerFormDialog } from "@/components/CustomerFormDialog";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { formatTaxId, money, toNumber } from "@/lib/format";
import { fetchAllInvoices } from "@/lib/invoices";

const CUSTOMERS_POLL_MS = 30_000;

function normalizeCustomerKey(name: string | null | undefined): string {
  return (name ?? "").trim().toLowerCase();
}

function customerMatchesInvoice(customer: Customer, invoiceCustomer: string | null): boolean {
  const key = normalizeCustomerKey(invoiceCustomer);
  if (!key) return false;
  const name = normalizeCustomerKey(customer.customer_name);
  const slug = customer.customer_slug.replace(/-/g, " ");
  return key === name || key.includes(name) || name.includes(key) || key.includes(slug);
}

function buildInvoiceStats(invoices: Invoice[]): Map<string, { amount: number; count: number }> {
  const map = new Map<string, { amount: number; count: number }>();
  for (const inv of invoices) {
    const key = normalizeCustomerKey(inv.vendor);
    if (!key) continue;
    const entry = map.get(key) ?? { amount: 0, count: 0 };
    entry.amount += toNumber(inv.total);
    entry.count += 1;
    map.set(key, entry);
  }
  return map;
}

/** Email/sender patterns used to match inbound sales documents. */
export function CustomerRegistryPanel() {
  const { user } = useAuth();
  const [rows, setRows] = useState<Customer[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editCustomer, setEditCustomer] = useState<Customer | null>(null);

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const fresh = options?.fresh ?? !options?.silent;
      const [customers, invoiceRows] = await Promise.all([
        api.listCustomers({ fresh }),
        fetchAllInvoices(fresh),
      ]);
      setRows(customers);
      setInvoices(invoiceRows);
    } catch (e) {
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load customers");
        setRows([]);
        setInvoices([]);
      }
    } finally {
      if (!options?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, user?.tenant_id]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, CUSTOMERS_POLL_MS);

  const statsByCustomer = useMemo(() => buildInvoiceStats(invoices), [invoices]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (c) =>
        c.customer_name.toLowerCase().includes(q) ||
        c.customer_slug.toLowerCase().includes(q) ||
        (c.abn ?? "").includes(q) ||
        c.sender_pattern.toLowerCase().includes(q)
    );
  }, [rows, search]);

  const lookupStats = (customer: Customer) => {
    for (const [key, stats] of statsByCustomer) {
      if (customerMatchesInvoice(customer, key)) return stats;
    }
    return { amount: 0, count: 0 };
  };

  const saveCustomer = async (body: Omit<Customer, "id" | "created_at">) => {
    if (editCustomer) {
      await api.updateCustomer(editCustomer.id, body);
    } else {
      await api.createCustomer(body);
    }
    await load({ fresh: true });
  };

  if (loading) {
    return (
      <Card className="p-8 text-center text-sm text-muted-foreground" data-testid="customer-registry-loading">
        Loading capture registry…
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="customer-registry-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Match inbound sales documents by email sender or domain. Use this for capture routing;
          GL defaults and billing live under Customer masters.
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => void load({ fresh: true })}>
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setEditCustomer(null);
              setFormOpen(true);
            }}
          >
            <Plus className="h-4 w-4 mr-1" />
            Add registry entry
          </Button>
        </div>
      </div>

      {error ? (
        <Card className="p-3 text-sm text-destructive border-destructive/30">{error}</Card>
      ) : null}

      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search capture registry…"
          className="pl-9 h-9"
          data-testid="input-customers-search"
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="No capture registry entries"
          hint="Add sender patterns manually, or promote a pending customer (registry row is created when the source invoice has an email sender)."
          action={
            <Button
              size="sm"
              onClick={() => {
                setEditCustomer(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add registry entry
            </Button>
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="px-4 py-2 font-medium">Customer</th>
                <th className="px-3 py-2 font-medium">Sender pattern</th>
                <th className="px-3 py-2 font-medium">ABN</th>
                <th className="px-3 py-2 font-medium text-right">Invoices</th>
                <th className="px-3 py-2 font-medium text-right">Revenue</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((customer) => {
                const stats = lookupStats(customer);
                return (
                  <tr
                    key={customer.id}
                    className="border-b border-border/60 last:border-0"
                    data-testid={`customer-row-${customer.id}`}
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-medium flex items-center gap-2">
                        <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
                        {customer.customer_name}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">{customer.customer_slug}</div>
                    </td>
                    <td className="px-3 py-2.5 text-xs">{customer.sender_pattern}</td>
                    <td className="px-3 py-2.5 font-mono text-xs">
                      {customer.abn ? formatTaxId(customer.abn) : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right tnum">{stats.count}</td>
                    <td className="px-3 py-2.5 text-right tnum font-medium">
                      {money(stats.amount)}
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge
                        variant="outline"
                        className={cn(
                          "font-normal",
                          customer.approved
                            ? "border-primary/40 text-primary"
                            : "border-destructive/40 text-destructive"
                        )}
                      >
                        {customer.approved ? "Approved" : "Pending"}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right space-x-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7"
                        onClick={() => {
                          setEditCustomer(customer);
                          setFormOpen(true);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-destructive"
                        onClick={async () => {
                          if (!window.confirm(`Delete ${customer.customer_name}?`)) return;
                          await api.deleteCustomer(customer.id);
                          await load({ fresh: true });
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      <CustomerFormDialog
        open={formOpen}
        customer={editCustomer}
        onClose={() => {
          setFormOpen(false);
          setEditCustomer(null);
        }}
        onSave={saveCustomer}
      />
    </div>
  );
}
