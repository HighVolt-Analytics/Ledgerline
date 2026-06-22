import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogoBlock } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { selectClassMd } from "@/lib/selectClass";
import {
  COUNTRIES,
  INDUSTRIES,
  countryByCode,
  vaultPreview,
  type Industry,
} from "@/data/orgSetup.tsx";
import { cn } from "@/lib/cn";

export function SetupPage() {
  const navigate = useNavigate();

  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [countryCode, setCountryCode] = useState("AU");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const country = countryByCode(countryCode);
  const preview = vaultPreview(industry);

  function goToSignIn() {
    navigate("/login", { replace: true });
  }

  function createOrg() {
    if (!businessName.trim()) {
      setError("Business name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    navigate("/login", {
      replace: true,
      state: {
        mode: "register",
        tenant_name: businessName.trim(),
        tenant_slug: businessName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
        email: email.trim() || undefined,
      },
    });
  }

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center bg-background px-4 py-8">
      {/* Logo */}
      <div className="mb-8">
        <LogoBlock />
      </div>

      {/* Card */}
      <div className="w-full max-w-lg rounded-xl border border-border bg-card p-8 shadow-lg">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight">Set up your organisation</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Your profile drives currency, tax rules, and your document vault structure.
          </p>
        </div>

        <div className="space-y-5">
          {/* Business name */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="setup-business-name">
              Business name
            </label>
            <Input
              id="setup-business-name"
              data-testid="input-business-name"
              placeholder="Acme Pty Ltd"
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
            />
          </div>

          {/* Industry + Country */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-industry">
                Industry
              </label>
              <Select
                id="setup-industry"
                data-testid="select-industry"
                value={industry}
                onValueChange={(v) => setIndustry(v as Industry)}
                size="md"
                options={INDUSTRIES.map((ind) => ({ value: ind, label: ind }))}
                className="w-full"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-country">
                Business country
              </label>
              <Select
                id="setup-country"
                data-testid="select-country"
                value={countryCode}
                onValueChange={setCountryCode}
                size="md"
                options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground tnum">
                {country.currency} {country.symbol} · {country.taxLabel} {country.taxRate}%
              </p>
            </div>
          </div>

          {/* Email + Phone */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-email">
                Email
              </label>
              <Input
                id="setup-email"
                type="email"
                data-testid="input-email"
                placeholder="accounts@acme.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="setup-phone">
                Phone
              </label>
              <div className="flex gap-2">
                <span
                  className={cn(
                    selectClassMd,
                    "w-14 shrink-0 flex items-center justify-center text-muted-foreground px-2"
                  )}
                >
                  {country.dialCode}
                </span>
                <Input
                  id="setup-phone"
                  type="tel"
                  data-testid="input-phone"
                  placeholder="400 000 000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* Vault preview */}
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Vault preview · {industry}:</span>{" "}
            {preview}…
          </div>

          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}

          {/* Actions */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <button
              type="button"
              data-testid="link-use-sample"
              className="text-sm text-primary hover:underline underline-offset-2"
              onClick={goToSignIn}
            >
              Already have an account? Sign in
            </button>
            <Button
              data-testid="button-create-org"
              onClick={createOrg}
              disabled={busy || !businessName.trim()}
            >
              {busy ? "Creating…" : "Create organisation"}
            </Button>
          </div>
        </div>
      </div>

      {/* Trust bar */}
      <p className="mt-6 text-[11px] text-muted-foreground">
        SOC 2 Type II · ISO 27001 · Bank-level encryption
      </p>
    </div>
  );
}
