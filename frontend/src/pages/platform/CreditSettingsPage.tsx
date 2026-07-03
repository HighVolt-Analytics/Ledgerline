import { useCallback, useEffect, useState } from "react";
import { Settings2 } from "lucide-react";
import { api } from "@/api/client";
import type { PlatformCreditSettings } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NumericInput } from "@/components/ui/numeric-input";

export function CreditSettingsPage() {
  const [settings, setSettings] = useState<PlatformCreditSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .getPlatformCreditSettings()
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(t);
  }, [saved]);

  async function save() {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updatePlatformCreditSettings(settings);
      setSettings(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !settings) {
    return (
      <div>
        <PageHeader title="Credit settings" subtitle="Global credit rules for all tenants." />
        <PageLoader label="Loading settings…" />
      </div>
    );
  }

  if (!settings) {
    return (
      <div>
        <PageHeader title="Credit settings" subtitle="Global credit rules for all tenants." />
        <p className="text-sm text-destructive">{error ?? "Settings unavailable"}</p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Credit settings"
        subtitle="Credits per page, top-up conversion, and per-tenant overrides."
      />

      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}
      {saved && <p className="mb-3 text-sm text-[hsl(var(--chart-1))]">Settings saved.</p>}

      <Card className="p-5 max-w-xl space-y-5">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Settings2 className="h-4 w-4" />
          Credits per page
        </div>

        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium">Universal credits per page</p>
            <p className="text-xs text-muted-foreground">
              When on, all tenants use the global rate below. When off, set credits per page on
              each client&apos;s tenant settings page.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={settings.universal_credits_per_page}
            onClick={() =>
              setSettings((s) =>
                s ? { ...s, universal_credits_per_page: !s.universal_credits_per_page } : s
              )
            }
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border border-transparent transition-colors ${
              settings.universal_credits_per_page ? "bg-primary" : "bg-input"
            }`}
          >
            <span
              className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform mt-0.5 ${
                settings.universal_credits_per_page ? "translate-x-4" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        {!settings.universal_credits_per_page && (
          <p className="text-xs text-[hsl(var(--chart-1))]">
            Per-tenant overrides are enabled. Open any client under Clients and edit credits per
            page in the Usage &amp; billing section.
          </p>
        )}

        <div>
          <label className="text-sm font-medium">Global credits per page</label>
          <NumericInput
            value={settings.credits_per_page}
            onValueChange={(n) =>
              setSettings((s) => (s && n != null ? { ...s, credits_per_page: n } : s))
            }
            wrapperClassName="mt-1 w-32"
          />
        </div>

        <div className="border-t border-border pt-4 space-y-3">
          <p className="text-sm font-semibold">Top-up conversion (currency → credits)</p>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">India (INR)</label>
              <NumericInput
                value={settings.topup_factor_in}
                onValueChange={(n) =>
                  setSettings((s) => (s && n != null ? { ...s, topup_factor_in: n } : s))
                }
                wrapperClassName="mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Singapore (SGD)</label>
              <NumericInput
                value={settings.topup_factor_sg}
                onValueChange={(n) =>
                  setSettings((s) => (s && n != null ? { ...s, topup_factor_sg: n } : s))
                }
                wrapperClassName="mt-1"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Australia (AUD)</label>
              <NumericInput
                value={settings.topup_factor_au}
                onValueChange={(n) =>
                  setSettings((s) => (s && n != null ? { ...s, topup_factor_au: n } : s))
                }
                wrapperClassName="mt-1"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Defaults: 1 INR = 1 credit · 1 SGD = 10 credits · 1 AUD = 5 credits
          </p>
        </div>

        <Button onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : "Save settings"}
        </Button>
      </Card>
    </div>
  );
}
