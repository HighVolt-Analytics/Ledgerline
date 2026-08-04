import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { INDUSTRIES, SelectField, type Industry } from "@/data/orgSetup.tsx";
import { useSetupCatalogs } from "@/hooks/useSetupCatalogs";

type CreateTenantWizardProps = {
  open: boolean;
  onClose: () => void;
  onCreated: (tenantId: string) => void;
};

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 100);
}

const STEPS = ["Organisation", "First admin", "Review"] as const;

export function CreateTenantWizard({ open, onClose, onCreated }: CreateTenantWizardProps) {
  const { countries, currencies } = useSetupCatalogs();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [country, setCountry] = useState("SG");
  const [currency, setCurrency] = useState("SGD");
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [industry, setIndustry] = useState<Industry>("Hospitality");
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setName("");
    setSlug("");
    setSlugTouched(false);
    setCountry("SG");
    setCurrency("SGD");
    setCurrencyTouched(false);
    setIndustry("Hospitality");
    setAdminName("");
    setAdminEmail("");
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!slugTouched) setSlug(slugify(name));
  }, [name, slugTouched]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  const currencyAllow = new Set(currencies.map((c) => c.code));
  const countryLabel = countries.find((c) => c.code === country)?.name ?? country;
  const currencyMeta =
    currencies.find((c) => c.code === currency) ??
    currencies[0] ?? { code: currency, symbol: "", name: currency };

  function validateStep(current: number): string | null {
    if (current === 0) {
      if (!name.trim()) return "Client name is required.";
      if (!slug.trim()) return "Slug is required.";
      if (!currency.trim()) return "Select a currency.";
      if (!currencyAllow.has(currency.trim().toUpperCase())) {
        return "Select a supported currency.";
      }
      return null;
    }
    if (current === 1) {
      if (!adminName.trim()) return "Admin name is required.";
      if (!adminEmail.trim()) return "Admin email is required.";
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(adminEmail.trim())) {
        return "Enter a valid email address.";
      }
      return null;
    }
    return null;
  }

  function goNext() {
    const err = validateStep(step);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }

  function goBack() {
    setError(null);
    setStep((s) => Math.max(s - 1, 0));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const err = validateStep(1);
    if (err) {
      setError(err);
      setStep(1);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const tenant = await api.createPlatformTenant({
        name: name.trim(),
        slug: slug.trim().toLowerCase(),
        country,
        currency,
        industry,
        first_admin_email: adminEmail.trim(),
        first_admin_name: adminName.trim(),
      });
      onCreated(tenant.id);
      onClose();
    } catch (submitErr) {
      setError(submitErr instanceof Error ? submitErr.message : "Could not create tenant");
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className="app-modal-root" role="presentation">
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Close dialog"
        onClick={onClose}
        disabled={busy}
      />
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-tenant-title"
        className="app-modal-panel p-6 space-y-4 max-w-lg w-full"
        data-testid="dialog-create-tenant"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="create-tenant-title" className="text-lg font-semibold leading-none">
              Create client tenant
            </h2>
            <p className="text-sm text-muted-foreground mt-2">
              Step {step + 1} of {STEPS.length}: {STEPS[step]}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-sm p-1 opacity-70 hover:opacity-100 transition-opacity shrink-0"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex gap-1">
          {STEPS.map((label, i) => (
            <div
              key={label}
              className={`h-1 flex-1 rounded-full ${i <= step ? "bg-primary" : "bg-muted"}`}
              aria-hidden
            />
          ))}
        </div>

        {step === 0 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="tenant-name">
                Client name
              </label>
              <Input
                id="tenant-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Hospitality Pty Ltd"
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="tenant-slug">
                Slug
              </label>
              <Input
                id="tenant-slug"
                value={slug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
                }}
                placeholder="acme-hospitality"
                pattern="[-a-z0-9]+"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Country</label>
              <SelectField
                value={country}
                onChange={(code) => {
                  setCountry(code);
                  if (!currencyTouched) {
                    const match = countries.find((c) => c.code === code);
                    setCurrency(match?.defaultCurrency || currency);
                  }
                }}
                options={countries.map((c) => ({ value: c.code, label: c.name }))}
                testId="select-country"
                searchable
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Currency</label>
              <SelectField
                value={currency}
                onChange={(code) => {
                  setCurrencyTouched(true);
                  setCurrency(code);
                }}
                options={currencies.map((c) => ({
                  value: c.code,
                  label: `${c.code}${c.symbol ? ` (${c.symbol})` : ""}`,
                }))}
                testId="select-currency"
                searchable
              />
              <p className="text-xs text-muted-foreground tnum">
                {currencyMeta.code}
                {currencyMeta.symbol ? ` ${currencyMeta.symbol}` : ""} — books / reporting currency
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Industry</label>
              <SelectField
                value={industry}
                onChange={(v) => setIndustry(v as Industry)}
                options={INDUSTRIES.map((i) => ({ value: i, label: i }))}
                testId="select-industry"
              />
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Invite the first client administrator. They will receive an email to set their
              password and complete onboarding.
            </p>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="admin-name">
                Admin full name
              </label>
              <Input
                id="admin-name"
                value={adminName}
                onChange={(e) => setAdminName(e.target.value)}
                placeholder="Jane Smith"
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="admin-email">
                Admin email
              </label>
              <Input
                id="admin-email"
                type="email"
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                placeholder="jane@client.com"
                required
              />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3 text-sm rounded-md border border-border p-4 bg-muted/30">
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Organisation</span>
              <span className="font-medium text-right">{name}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Slug</span>
              <span className="font-mono text-xs">{slug}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Country</span>
              <span>{countryLabel}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Currency</span>
              <span>
                {currencyMeta.code}
                {currencyMeta.symbol ? ` (${currencyMeta.symbol})` : ""}
              </span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Industry</span>
              <span>{industry}</span>
            </div>
            <div className="h-px bg-border my-2" />
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">First admin</span>
              <span className="text-right">
                {adminName}
                <br />
                <span className="text-muted-foreground text-xs">{adminEmail}</span>
              </span>
            </div>
            <p className="text-xs text-muted-foreground pt-1">
              An invitation email will be sent. The tenant will start with 0 users until the admin
              accepts.
            </p>
          </div>
        )}

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-between gap-2 pt-1">
          <div>
            {step > 0 && (
              <Button type="button" variant="outline" onClick={goBack} disabled={busy}>
                <ChevronLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            {step < STEPS.length - 1 ? (
              <Button type="button" onClick={goNext} disabled={busy}>
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create & send invite"}
              </Button>
            )}
          </div>
        </div>
      </form>
    </div>,
    document.body
  );
}
