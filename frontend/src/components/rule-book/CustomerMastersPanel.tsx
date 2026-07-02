import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/context/ToastContext";
import {
  useCreateCustomerMaster,
  useCustomerMasters,
  useDeleteCustomerMaster,
  useUpdateCustomerMaster,
} from "@/hooks/useMasterData";
import { cn } from "@/lib/cn";
import { fmtAud } from "@/lib/v4MockData";
import type { CustomerMaster } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { CustomerDetailPanel } from "./CustomerDetailPanel";

function StatusDot({ status }: { status: string }) {
  const tone: Record<string, string> = {
    Active: "bg-[hsl(var(--chart-1))]",
    "On hold": "bg-[hsl(43_74%_49%)]",
    "Pending registration": "bg-destructive",
  };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
      <span className={cn("h-2 w-2 rounded-full shrink-0", tone[status] ?? "bg-muted-foreground")} />
      {status}
    </span>
  );
}

/** GL defaults, aliases, and billing used in sales routing. */
export function CustomerMastersPanel() {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, CustomerMaster>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [quickName, setQuickName] = useState("");

  const { data: customers = [], isLoading } = useCustomerMasters();
  const createMutation = useCreateCustomerMaster();
  const updateMutation = useUpdateCustomerMaster();
  const deleteMutation = useDeleteCustomerMaster();

  const getDraft = (customer: CustomerMaster) => drafts[customer.id] ?? customer;

  const patchDraft = (id: string, patch: Partial<CustomerMaster>) => {
    setDrafts((prev) => {
      const base = prev[id] ?? customers.find((c) => c.id === id)!;
      return { ...prev, [id]: { ...base, ...patch } };
    });
    setDirtyIds((prev) => new Set(prev).add(id));
  };

  const saveCustomer = async (id: string) => {
    const draft = drafts[id];
    if (!draft) return;
    try {
      await updateMutation.mutateAsync({ id, patch: draft });
      setDirtyIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      toast({ title: "Customer saved" });
    } catch (err) {
      toast({
        title: "Could not save customer",
        description: err instanceof Error ? err.message : "Save failed",
        variant: "destructive",
      });
    }
  };

  const addCustomer = async () => {
    const name = quickName.trim();
    if (!name) return;
    try {
      const created = await createMutation.mutateAsync({ name });
      setQuickName("");
      setExpandedId(created.id);
      toast({ title: "Customer added" });
    } catch (err) {
      toast({
        title: "Could not add customer",
        description: err instanceof Error ? err.message : "Create failed",
        variant: "destructive",
      });
    }
  };

  const removeCustomer = async (customer: CustomerMaster) => {
    if (!window.confirm(`Delete customer ${customer.name}?`)) return;
    try {
      await deleteMutation.mutateAsync(customer.id);
      toast({ title: "Customer deleted" });
    } catch (err) {
      toast({
        title: "Could not delete customer",
        description: err instanceof Error ? err.message : "Delete failed",
        variant: "destructive",
      });
    }
  };

  if (isLoading) {
    return <div className="text-sm text-muted-foreground py-8">Loading customer masters…</div>;
  }

  return (
    <div className="space-y-4" data-testid="customer-masters-panel">
      <p className="text-sm text-muted-foreground max-w-2xl">
        Canonical customer records for sales GL routing, aliases, and billing. For email sender
        matching, use Capture registry.
      </p>

      <Card className="p-3 flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[200px]">
          <div className="text-xs text-muted-foreground mb-1">Quick add customer</div>
          <Input
            value={quickName}
            onChange={(e) => setQuickName(e.target.value)}
            placeholder="Customer legal name"
            className="h-8 text-sm"
            data-testid="input-quick-customer-name"
          />
        </div>
        <Button
          size="sm"
          onClick={() => void addCustomer()}
          disabled={createMutation.isPending || !quickName.trim()}
          data-testid="button-add-customer-master"
        >
          {createMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <>
              <Plus className="h-4 w-4 mr-1" /> Add
            </>
          )}
        </Button>
      </Card>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b border-border">
              <th className="px-4 py-2 font-medium w-8" />
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">ABN</th>
              <th className="px-3 py-2 font-medium">Default GL</th>
              <th className="px-3 py-2 font-medium text-right">Revenue YTD</th>
              <th className="px-3 py-2 font-medium">Confidence</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {customers.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">
                  No customer masters yet.
                </td>
              </tr>
            ) : (
              customers.map((customer) => {
                const draft = getDraft(customer);
                const expanded = expandedId === customer.id;
                const dirty = dirtyIds.has(customer.id);
                return (
                  <Fragment key={customer.id}>
                    <tr className="border-b border-border/60 hover-elevate">
                      <td className="px-4 py-2">
                        <button
                          type="button"
                          className="text-muted-foreground"
                          onClick={() => setExpandedId(expanded ? null : customer.id)}
                        >
                          {expanded ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                      <td className="px-3 py-2 font-medium">{customer.name}</td>
                      <td className="px-3 py-2 font-mono text-xs">{customer.abn || "—"}</td>
                      <td className="px-3 py-2">
                        <AccountBadge account={customer.defaultLedger || "Suspense Account"} />
                      </td>
                      <td className="px-3 py-2 text-right tnum">{fmtAud(customer.totalRevenueYTD)}</td>
                      <td className="px-3 py-2 w-28">
                        <ConfidenceBar value={customer.matchConfidence} />
                      </td>
                      <td className="px-3 py-2">
                        <StatusDot status={customer.status} />
                      </td>
                      <td className="px-4 py-2 text-right space-x-1">
                        {dirty ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            disabled={updateMutation.isPending}
                            onClick={() => void saveCustomer(customer.id)}
                          >
                            Save
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-destructive"
                          onClick={() => void removeCustomer(customer)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr>
                        <td colSpan={8} className="p-0">
                          <CustomerDetailPanel
                            customer={draft}
                            onChange={(patch) => patchDraft(customer.id, patch)}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
