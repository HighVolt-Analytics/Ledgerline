import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { COUNTRIES, INDUSTRIES, SelectField, type Industry } from "@/data/orgSetup.tsx";
import { useAuth } from "@/context/AuthContext";
import { canRenderTenantOwnedUi, captureTenantFetchScope, isTenantFetchScopeCurrent } from "@/lib/tenantSession";

export function OnboardingPage() {
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const [country, setCountry] = useState("SG");
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.onboarding_completed) {
      navigate("/", { replace: true });
      return;
    }
    if (user?.is_support_session) {
      navigate("/", { replace: true });
      return;
    }
    if (!canRenderTenantOwnedUi(user?.tenant_id)) return;
    const scope = captureTenantFetchScope();
    void api
      .getOnboardingStatus()
      .then((status) => {
        if (!isTenantFetchScopeCurrent(scope)) return;
        if (status.completed) {
          navigate("/", { replace: true });
          return;
        }
        setCountry(status.country || "SG");
        if (status.industry && INDUSTRIES.includes(status.industry as Industry)) {
          setIndustry(status.industry as Industry);
        }
      })
      .catch(() => setError("Could not load onboarding status"))
      .finally(() => setLoading(false));
  }, [user, navigate]);

  async function completeSetup() {
    setBusy(true);
    setError(null);
    try {
      await api.updateOnboarding({
        country,
        industry,
        complete: true,
      });
      await refreshUser();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save setup");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center bg-background px-4 py-8">
      <div className="mb-8">
        <LogoBlock />
      </div>

      <Card className="w-full max-w-lg p-8 space-y-6">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Welcome to {user?.tenant_name}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Confirm your organisation profile to finish setup. You can invite more team members
            from settings later.
          </p>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Country</label>
            <SelectField
              value={country}
              onChange={setCountry}
              options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
              testId="onboarding-country"
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Industry</label>
            <SelectField
              value={industry}
              onChange={(v) => setIndustry(v as Industry)}
              options={INDUSTRIES.map((i) => ({ value: i, label: i }))}
              testId="onboarding-industry"
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="flex flex-col sm:flex-row gap-2">
          <Button className="flex-1" disabled={busy} onClick={() => void completeSetup()}>
            {busy ? "Saving…" : "Complete setup"}
          </Button>
          <Link
            to="/settings?tab=team"
            className="inline-flex flex-1 items-center justify-center rounded-md border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-accent transition-colors"
          >
            Invite team members
          </Link>
        </div>
      </Card>
    </div>
  );
}
