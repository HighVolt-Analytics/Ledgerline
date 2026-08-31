import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { RuleBookDocumentTypesSection } from "@/components/rule-book/RuleBookDocumentTypesSection";
import { ApprovalPolicyPrivileges } from "@/components/settings/ApprovalPolicyPrivileges";
import { ChartOfAccountsPanel } from "@/components/settings/ChartOfAccountsPanel";
import { TaxRatesPanel } from "@/components/settings/TaxRatesPanel";
import { OrgAiBriefPanel } from "@/components/settings/OrgAiBriefPanel";
import { TenantMembersSection } from "@/components/settings/TenantMembersSection";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { notifyOnboardingStatusRefresh } from "@/components/onboarding/OnboardingChecklist";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/queryClient";
import { INDUSTRIES } from "@/lib/settingsData";
import { SETTINGS_TABS, type SettingsTabId } from "@/lib/settingsTabs";
import { useSetupCatalogs } from "@/hooks/useSetupCatalogs";

export function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab = SETTINGS_TABS.find((t) => t.id === tabParam)?.id ?? "profile";
  const [tab, setTab] = useState<SettingsTabId>(initialTab);
  const [saved, setSaved] = useState(false);
  const [aiBriefSaved, setAiBriefSaved] = useState(false);
  const [coaSaved, setCoaSaved] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<string>("");
  const [country, setCountry] = useState("");
  const [currency, setCurrency] = useState("");
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [initialCurrency, setInitialCurrency] = useState("");
  const [laborRatePerHour, setLaborRatePerHour] = useState("45");
  const { countries, currencies } = useSetupCatalogs();
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [timezone, setTimezone] = useState("");
  const [locale, setLocale] = useState("");
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);
  const {
    data: institution,
    isLoading: institutionLoading,
    blocked: institutionBlocked,
  } = useInstitutionSettings(Boolean(user));

  useResetOnTenantChange(() => {
    setBusinessName("");
    setIndustry("");
    setCountry("");
    setCurrency("");
    setCurrencyTouched(false);
    setInitialCurrency("");
    setLaborRatePerHour("45");
    setPhone("");
    setTimezone("");
    setLocale("");
    setSaved(false);
  });

  useEffect(() => {
    const next = SETTINGS_TABS.find((t) => t.id === tabParam)?.id ?? "profile";
    setTab(next);
  }, [tabParam]);
  useEffect(() => {
    if (!user) {
      setProfileLoading(false);
      return;
    }
    setEmail(user.email);
    setProfileLoading(institutionLoading || institutionBlocked);
  }, [user, institutionLoading, institutionBlocked]);

  useEffect(() => {
    if (!user || institutionBlocked || institutionLoading) {
      if (!user) setProfileLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const onboarding = await api.getOnboardingStatus();
        if (!cancelled && onboarding.industry) {
          setIndustry(onboarding.industry);
        }
      } catch {
        /* keep current industry selection */
      }
      if (cancelled) return;
      if (institution) {
        setBusinessName(institution.name);
        setCountry(institution.country);
        setCurrency(institution.currency || defaultFromCountry(institution.country));
        setInitialCurrency(institution.currency || defaultFromCountry(institution.country));
        setCurrencyTouched(false);
        setTimezone(institution.timezone);
        setLocale(institution.locale || "");
        setLaborRatePerHour(
          String(
            institution.labor_rate_per_hour != null && institution.labor_rate_per_hour > 0
              ? institution.labor_rate_per_hour
              : 45
          )
        );
        setProfileLoading(false);
        return;
      }
      setBusinessName(user.tenant_name);
      setCountry("");
      setCurrency("");
      setInitialCurrency("");
      setTimezone(user.tenant_timezone);
      setLocale("");
      setProfileLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [user, institution, institutionBlocked, institutionLoading, tenantScope, countries]);

  function defaultFromCountry(code: string): string {
    return countries.find((c) => c.code === code)?.defaultCurrency || "";
  }

  function catalogForCountry(code: string) {
    return countries.find((c) => c.code === code);
  }

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 3000);
    return () => clearTimeout(t);
  }, [saved]);

  useEffect(() => {
    if (!aiBriefSaved) return;
    const t = setTimeout(() => setAiBriefSaved(false), 3000);
    return () => clearTimeout(t);
  }, [aiBriefSaved]);

  useEffect(() => {
    if (!coaSaved) return;
    const t = setTimeout(() => setCoaSaved(false), 3000);
    return () => clearTimeout(t);
  }, [coaSaved]);

  const countryMeta =
    countries.find((c) => c.code === country) ??
    countries[0] ?? {
      code: country,
      name: country,
      defaultCurrency: currency,
      taxLabel: "Tax",
      taxRate: null as number | null,
      dialCode: "",
      timeZone: timezone,
      locale: "en",
    };
  const currencyMeta =
    currencies.find((c) => c.code === currency) ??
    currencies[0] ?? { code: currency, symbol: "", name: currency, decimalPlaces: 2 };
  const displayTimezone = countryMeta.timeZone || timezone;
  const canEditAdmin = user?.role === "admin";

  const saveProfile = async () => {
    const trimmedName = businessName.trim();
    if (!trimmedName) {
      toast({ title: "Business name is required", variant: "destructive" });
      return;
    }
    const currencyChanged =
      currency.trim().toUpperCase() !== (initialCurrency || "").trim().toUpperCase();
    if (
      currencyChanged &&
      institution?.has_ledger_activity &&
      !window.confirm(
        "Changing books currency after documents exist is a functional currency change. Historical amounts are not revalued. Continue?"
      )
    ) {
      return;
    }
    const countryMatch = catalogForCountry(country);
    const nextTimezone = countryMatch?.timeZone || timezone || undefined;
    const nextLocale = countryMatch?.locale || locale || undefined;
    const parsedLabor = Number.parseFloat(laborRatePerHour);
    if (!Number.isFinite(parsedLabor) || parsedLabor <= 0) {
      toast({ title: "Labor cost per hour must be a positive number", variant: "destructive" });
      return;
    }
    setProfileSaving(true);
    try {
      const inst = await api.updateInstitutionSettings({
        name: trimmedName,
        country,
        currency,
        labor_rate_per_hour: parsedLabor,
        ...(nextTimezone ? { timezone: nextTimezone } : {}),
        ...(nextLocale ? { locale: nextLocale } : {}),
      });
      const onboarding = await api.updateOnboarding({ industry: industry || undefined });
      setBusinessName(inst.name);
      setCountry(inst.country);
      setCurrency(inst.currency);
      setInitialCurrency(inst.currency);
      setCurrencyTouched(false);
      setTimezone(inst.timezone);
      setLocale(inst.locale || "");
      setLaborRatePerHour(
        String(
          inst.labor_rate_per_hour != null && inst.labor_rate_per_hour > 0
            ? inst.labor_rate_per_hour
            : parsedLabor
        )
      );
      if (onboarding.industry) setIndustry(onboarding.industry);
      await queryClient.invalidateQueries({ queryKey: queryKeys.institutionSettings() });
      await refreshUser();
      setSaved(true);
      notifyOnboardingStatusRefresh();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not save profile settings";
      toast({ title: message, variant: "destructive" });
    } finally {
      setProfileSaving(false);
    }
  };

  return (
    <div>
      {saved && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md">
          Profile updated
        </div>
      )}
      {aiBriefSaved && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md">
          AI brief saved
        </div>
      )}
      {coaSaved && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md">
          Chart of accounts saved
        </div>
      )}

      <PageHeader
        title="Settings"
        subtitle="Organisation profile, AI document brief, team, approval policy, chart of accounts, tax rates, and Rule Book."
      />

      <div className="app-underline-tabs mb-4" role="tablist" aria-label="Settings sections">
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={t.testid}
            onClick={() => {
              setSearchParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  next.set("tab", t.id);
                  return next;
                },
                { replace: true }
              );
            }}
            className={cn(
              "app-underline-tabs__tab",
              tab === t.id && "app-underline-tabs__tab--active"
            )}
            role="tab"
            aria-selected={tab === t.id}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "profile" && (
        <Card className="p-5 w-full max-w-none">
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="input-settings-name" className="text-sm font-medium">
                Business name
              </label>
              <Input
                id="input-settings-name"
                data-testid="input-settings-name"
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="select-settings-industry" className="text-sm font-medium">
                Industry
              </label>
              <Select
                id="select-settings-industry"
                data-testid="select-settings-industry"
                value={industry || INDUSTRIES[0]}
                onValueChange={setIndustry}
                size="md"
                options={INDUSTRIES.map((i) => ({ value: i, label: i }))}
                className="w-full"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="select-settings-country" className="text-sm font-medium">
                Country
              </label>
              <Select
                id="select-settings-country"
                data-testid="select-settings-country"
                value={country}
                onValueChange={(code) => {
                  setCountry(code);
                  const match = countries.find((c) => c.code === code);
                  if (match?.timeZone) setTimezone(match.timeZone);
                  if (match?.locale) setLocale(match.locale);
                  if (!currencyTouched) {
                    setCurrency(match?.defaultCurrency || currency);
                  }
                }}
                size="md"
                searchable
                options={countries.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="select-settings-currency" className="text-sm font-medium">
                Currency
              </label>
              <Select
                id="select-settings-currency"
                data-testid="select-settings-currency"
                value={currency}
                onValueChange={(code) => {
                  setCurrencyTouched(true);
                  setCurrency(code);
                }}
                size="md"
                searchable
                options={currencies.map((c) => ({
                  value: c.code,
                  label: `${c.code}${c.symbol ? ` (${c.symbol})` : ""} — ${c.name}`,
                }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground tnum">
                {currencyMeta.code}
                {currencyMeta.symbol ? ` ${currencyMeta.symbol}` : ""} · {countryMeta.taxLabel}
                {countryMeta.taxRate != null ? ` ${countryMeta.taxRate}%` : ""}
                {displayTimezone ? ` · ${displayTimezone}` : null}
              </p>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="input-settings-labor-rate" className="text-sm font-medium">
                Labor cost / hour
              </label>
              <Input
                id="input-settings-labor-rate"
                data-testid="input-settings-labor-rate"
                className="tnum"
                type="number"
                min={0.01}
                step="0.01"
                value={laborRatePerHour}
                onChange={(e) => setLaborRatePerHour(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Used for dashboard estimated cost saved ({currencyMeta.code}
                {currencyMeta.symbol ? ` ${currencyMeta.symbol}` : ""}).
              </p>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="input-settings-email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="input-settings-email"
                data-testid="input-settings-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="input-settings-phone" className="text-sm font-medium">
                Phone
              </label>
              <Input
                id="input-settings-phone"
                data-testid="input-settings-phone"
                className="tnum"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder={countryMeta.dialCode ? `${countryMeta.dialCode} …` : "Enter phone number"}
              />
            </div>
          </div>
          <div className="mt-5 flex justify-end">
            <Button
              data-testid="button-save-profile"
              onClick={() => void saveProfile()}
              disabled={profileLoading || profileSaving}
            >
              {profileSaving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </Card>
      )}

      {tab === "ai-documents" && (
        <>
          {!canEditAdmin ? (
            <p className="mb-3 text-sm text-muted-foreground">
              Only admins can edit the org AI brief.
            </p>
          ) : null}
          <OrgAiBriefPanel
            canEdit={canEditAdmin}
            onSaved={() => setAiBriefSaved(true)}
          />
        </>
      )}

      {tab === "rule-book" && <RuleBookDocumentTypesSection />}

      {tab === "team" && <TenantMembersSection />}
      {tab === "policy" && <ApprovalPolicyPrivileges />}
      {tab === "coa" && (
        <ChartOfAccountsPanel canEdit={canEditAdmin} onSaved={() => setCoaSaved(true)} />
      )}
      {tab === "tax-rates" && <TaxRatesPanel canEdit={canEditAdmin} />}
    </div>
  );
}
