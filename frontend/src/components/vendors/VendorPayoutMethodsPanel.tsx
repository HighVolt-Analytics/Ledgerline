import { useEffect, useState } from "react";
import { CreditCard, Plus, Trash2 } from "lucide-react";
import type {
  VendorPayoutMethod,
  VendorPayoutMethodStatus,
  VendorPayoutMethodType,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import {
  useVendorPayoutMethodMutations,
  useVendorPayoutMethods,
} from "@/hooks/useVendorPayoutMethods";

const METHOD_TYPES: { value: VendorPayoutMethodType; label: string }[] = [
  { value: "manual_bank", label: "Manual bank transfer" },
  { value: "stripe_connected_account", label: "Stripe connected account" },
  { value: "external_bank_phase2", label: "External bank (Phase 2)" },
];

const STATUSES: { value: VendorPayoutMethodStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "verified", label: "Verified" },
  { value: "disabled", label: "Disabled" },
];

function formatMethodType(value: string | null | undefined): string {
  return METHOD_TYPES.find((item) => item.value === value)?.label ?? value ?? "—";
}

function formatStatus(value: string | null | undefined): string {
  if (!value || value === "not_configured") return "Not configured";
  return STATUSES.find((item) => item.value === value)?.label ?? value;
}

function statusTone(status: string | null | undefined): string {
  if (status === "verified") {
    return "text-[hsl(var(--chart-1))] border-[hsl(var(--chart-1)/0.4)]";
  }
  if (status === "pending") {
    return "border-[rgb(var(--system-yellow-rgb)/0.35)] text-[var(--system-yellow-text)]";
  }
  if (status === "disabled") {
    return "border-destructive/40 text-destructive";
  }
  return "text-muted-foreground";
}

export function VendorPayoutMethodsPanel({ vendorId }: { vendorId: number }) {
  const { data: methods = [], isLoading, error } = useVendorPayoutMethods(vendorId);
  const { createMethod, updateMethod, deleteMethod } = useVendorPayoutMethodMutations(vendorId);
  const [showForm, setShowForm] = useState(false);
  const [methodType, setMethodType] = useState<VendorPayoutMethodType>("manual_bank");
  const [displayLabel, setDisplayLabel] = useState("");
  const [stripeAccountId, setStripeAccountId] = useState("");
  const [last4, setLast4] = useState("");
  const [status, setStatus] = useState<VendorPayoutMethodStatus>("pending");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!showForm) return;
    setFormError(null);
  }, [showForm, methodType]);

  async function handleCreate() {
    setFormError(null);
    try {
      await createMethod.mutateAsync({
        method_type: methodType,
        display_label: displayLabel.trim() || null,
        stripe_account_id:
          methodType === "stripe_connected_account" ? stripeAccountId.trim() || null : null,
        last4: last4.trim() || null,
        status,
        is_default: methods.length === 0,
      });
      setShowForm(false);
      setDisplayLabel("");
      setStripeAccountId("");
      setLast4("");
      setStatus("pending");
      setMethodType("manual_bank");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to save payout method");
    }
  }

  async function toggleDefault(method: VendorPayoutMethod) {
    if (method.is_default) return;
    await updateMethod.mutateAsync({
      methodId: method.id,
      body: { is_default: true },
    });
  }

  async function disableMethod(method: VendorPayoutMethod) {
    await updateMethod.mutateAsync({
      methodId: method.id,
      body: { status: "disabled", is_default: false },
    });
  }

  async function removeMethod(method: VendorPayoutMethod) {
    if (!window.confirm("Remove this payout method record?")) return;
    await deleteMethod.mutateAsync(method.id);
  }

  return (
    <div
      className="mt-5 border-t border-border pt-4"
      data-testid={`vendor-payout-methods-${vendorId}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-primary shrink-0" />
          <h5 className="text-sm font-medium">Payout method readiness</h5>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={() => setShowForm((value) => !value)}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add method
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground mb-3">
        Actual Stripe payouts are not enabled yet. This records payout readiness only.
      </p>

      {isLoading ? (
        <p className="text-xs text-muted-foreground">Loading payout methods…</p>
      ) : error ? (
        <p className="text-xs text-destructive">Could not load payout methods.</p>
      ) : methods.length === 0 ? (
        <p className="text-xs text-muted-foreground">No payout method recorded yet.</p>
      ) : (
        <div className="space-y-2">
          {methods.map((method) => (
            <div
              key={method.id}
              className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs"
              data-testid={`vendor-payout-method-${method.id}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium text-foreground">
                    {method.display_label || formatMethodType(method.method_type)}
                    {method.is_default ? (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-primary">
                        Default
                      </span>
                    ) : null}
                  </div>
                  <div className="text-muted-foreground mt-0.5">
                    {formatMethodType(method.method_type)}
                    {method.last4 ? ` · ••••${method.last4}` : ""}
                    {method.currency ? ` · ${method.currency}` : ""}
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                    statusTone(method.status)
                  )}
                >
                  {formatStatus(method.status)}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {!method.is_default && method.status !== "disabled" ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs px-2"
                    onClick={() => void toggleDefault(method)}
                    disabled={updateMethod.isPending}
                  >
                    Set default
                  </Button>
                ) : null}
                {method.status !== "disabled" ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs px-2"
                    onClick={() => void disableMethod(method)}
                    disabled={updateMethod.isPending}
                  >
                    Disable
                  </Button>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs px-2 text-destructive"
                  onClick={() => void removeMethod(method)}
                  disabled={deleteMethod.isPending}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showForm ? (
        <div className="mt-3 rounded-md border border-border bg-background p-3 space-y-2.5">
          <div>
            <label className="text-xs text-muted-foreground">Method type</label>
            <Select
              value={methodType}
              onValueChange={(value) => setMethodType(value as VendorPayoutMethodType)}
              options={METHOD_TYPES}
              size="sm"
              className="mt-1 w-full"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Display label</label>
            <Input
              value={displayLabel}
              onChange={(e) => setDisplayLabel(e.target.value)}
              placeholder="e.g. Primary AUD account"
              className="mt-1 h-8 text-xs"
            />
          </div>
          {methodType === "stripe_connected_account" ? (
            <div>
              <label className="text-xs text-muted-foreground">Stripe account id</label>
              <Input
                value={stripeAccountId}
                onChange={(e) => setStripeAccountId(e.target.value)}
                placeholder="acct_…"
                className="mt-1 h-8 text-xs font-mono"
              />
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground">Last 4 digits (optional)</label>
              <Input
                value={last4}
                onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))}
                placeholder="1234"
                className="mt-1 h-8 text-xs tnum"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Status</label>
              <Select
                value={status}
                onValueChange={(value) => setStatus(value as VendorPayoutMethodStatus)}
                options={STATUSES}
                size="sm"
                className="mt-1 w-full"
              />
            </div>
          </div>
          {formError ? <p className="text-xs text-destructive">{formError}</p> : null}
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="flex-1 h-8 text-xs"
              onClick={() => setShowForm(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              className="flex-1 h-8 text-xs"
              onClick={() => void handleCreate()}
              disabled={createMethod.isPending}
            >
              {createMethod.isPending ? "Saving…" : "Save method"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
