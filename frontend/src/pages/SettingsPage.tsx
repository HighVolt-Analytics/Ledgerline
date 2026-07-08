import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { ApprovalPolicyPrivileges } from "@/components/settings/ApprovalPolicyPrivileges";
import { ChartOfAccountsPanel } from "@/components/settings/ChartOfAccountsPanel";
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
import {
  COUNTRIES,
  INDUSTRIES,
  countryByCode,
} from "@/lib/settingsData";

const TABS = [
  { id: "profile", label: "Profile", testid: "tab-profile" },
  { id: "ai-documents", label: "AI & documents", testid: "tab-ai-documents" },
  { id: "team", label: "Team", testid: "tab-team" },
  { id: "policy", label: "Policy & privileges", testid: "tab-policy" },
  { id: "coa", label: "Chart of accounts", testid: "tab-coa" },
] as const;

export function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab = TABS.find((t) => t.id === tabParam)?.id ?? "profile";
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(initialTab);
  const [saved, setSaved] = useState(false);
  const [aiBriefSaved, setAiBriefSaved] = useState(false);
  const [coaSaved, setCoaSaved] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<string>(INDUSTRIES[1]);
  const [country, setCountry] = useState("AU");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [timezone, setTimezone] = useState("");
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);
  const {
    data: institution,
    isLoading: institutionLoading,
    blocked: institutionBlocked,
  } = useInstitutionSettings(Boolean(user));

  useResetOnTenantChange(() => {
    setBusinessName("");
    setIndustry(INDUSTRIES[1]);
    setCountry("AU");
    setPhone("");
    setTimezone("");
    setSaved(false);
  });

  useEffect(() => {
    const next = TABS.find((t) => t.id === tabParam)?.id ?? "profile";
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
    if (institution) {
      setBusinessName(institution.name);
      setCountry(institution.country);
      setTimezone(institution.timezone);
      setProfileLoading(false);
      return;
    }
    setBusinessName(user.tenant_name);
    setCountry("AU");
    setTimezone(user.tenant_timezone);
    setProfileLoading(false);
  }, [user, institution, institutionBlocked, institutionLoading, tenantScope]);

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

  const countryMeta = countryByCode(country);
  const canEditAdmin = user?.role === "admin";

  const saveProfile = async () => {
    const trimmedName = businessName.trim();
    if (!trimmedName) {
      toast({ title: "Business name is required", variant: "destructive" });
      return;
    }
    setProfileSaving(true);
    try {
      const inst = await api.updateInstitutionSettings({
        name: trimmedName,
        country,
      });
      await api.updateOnboarding({ industry });
      setBusinessName(inst.name);
      setCountry(inst.country);
      setTimezone(inst.timezone);
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

  return (    <div>
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
        subtitle="Organisation profile, AI document brief, team, approval policy, and chart of accounts."
      />

      <div className="flex flex-wrap gap-1 border-b border-border mb-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={t.testid}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "profile" && (
        <Card className="p-5 max-w-2xl">
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
                value={industry}
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
                  setTimezone(countryByCode(code).timeZone);
                }}
                size="md"
                options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground tnum">
                {countryMeta.currency} {countryMeta.symbol} · {countryMeta.taxLabel}{" "}
                {countryMeta.taxRate}%
                {timezone ? ` · ${timezone}` : null}
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
                placeholder={`${countryMeta.dialCode} …`}
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
            tenantName={businessName || user?.tenant_name}
            canEdit={canEditAdmin}
            onSaved={() => setAiBriefSaved(true)}
          />
        </>
      )}

      {tab === "team" && <TenantMembersSection />}
      {tab === "policy" && <ApprovalPolicyPrivileges />}

      {tab === "coa" && (
        <ChartOfAccountsPanel canEdit={canEditAdmin} onSaved={() => setCoaSaved(true)} />
      )}
    </div>
  );
}
