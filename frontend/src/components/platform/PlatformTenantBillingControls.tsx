import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import type { PlatformCreditSettings, PlatformTenantDetail } from "@/api/types";
import { Button } from "@/components/ui/button";
import { NumericInput } from "@/components/ui/numeric-input";

type Props = {
  tenant: PlatformTenantDetail;
  onUpdated: (tenant: PlatformTenantDetail) => void;
};

export function PlatformTenantBillingControls({ tenant, onUpdated }: Props) {
  const [creditSettings, setCreditSettings] = useState<PlatformCreditSettings | null>(null);
  const [override, setOverride] = useState<number | undefined>(
    tenant.credits_per_page_override ?? tenant.credits_per_page
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setOverride(tenant.credits_per_page_override ?? tenant.credits_per_page);
  }, [tenant.credits_per_page, tenant.credits_per_page_override, tenant.id]);

  useEffect(() => {
    setLoading(true);
    api
      .getPlatformCreditSettings()
      .then(setCreditSettings)
      .catch(() => setCreditSettings(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(t);
  }, [saved]);

  const universal = creditSettings?.universal_credits_per_page ?? true;
  const globalCpp = creditSettings?.credits_per_page ?? 5;
  const hasCustomOverride =
    tenant.credits_per_page_override != null &&
    tenant.credits_per_page_override !== globalCpp;

  async function saveOverride() {
    if (override == null || override < 1) {
      setError("Credits per page must be at least 1.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updatePlatformTenantBilling(tenant.id, {
        credits_per_page_override: override,
      });
      onUpdated(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save billing settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <p className="text-xs text-muted-foreground border-t border-border pt-4">
        Loading credit rules…
      </p>
    );
  }

  if (universal) {
    return (
      <div className="border-t border-border pt-4 space-y-1">
        <p className="text-sm font-medium">Credits per page</p>
        <p className="text-xs text-muted-foreground">
          Universal pricing is on — this tenant uses the global rate of{" "}
          <span className="font-semibold tnum">{globalCpp}</span> credits per page. Turn off
          universal pricing in{" "}
          <Link to="/platform/credit-settings" className="text-primary hover:underline">
            Credit settings
          </Link>{" "}
          to set a per-tenant override here.
        </p>
      </div>
    );
  }

  return (
    <div className="border-t border-border pt-4 space-y-3">
      <div>
        <p className="text-sm font-medium">Per-tenant credits per page</p>
        <p className="text-xs text-muted-foreground mt-1">
          Universal pricing is off. Set a custom rate for this tenant (global default is{" "}
          {globalCpp}). Effective rate now:{" "}
          <span className="font-semibold tnum">{tenant.credits_per_page}</span>
          {hasCustomOverride ? " (custom)" : " (using global default)"}.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="text-xs text-muted-foreground">
            Credits per page
          </label>
          <NumericInput
            value={override}
            onValueChange={setOverride}
            wrapperClassName="mt-1 w-32"
          />
        </div>
        <Button
          type="button"
          size="sm"
          disabled={saving || override == null}
          onClick={() => void saveOverride()}
        >
          {saving ? "Saving…" : "Save credits / page"}
        </Button>
      </div>

      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p className="text-xs text-[hsl(var(--chart-1))]">Per-tenant credits per page saved.</p>
      )}
    </div>
  );
}
