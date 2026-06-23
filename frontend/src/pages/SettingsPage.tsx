import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { ApprovalPolicyPrivileges } from "@/components/settings/ApprovalPolicyPrivileges";
import { TenantMembersSection } from "@/components/settings/TenantMembersSection";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/cn";
import {
  CHART_OF_ACCOUNTS,
  COUNTRIES,
  INDUSTRIES,
  countryByCode,
} from "@/lib/settingsData";

const TABS = [
  { id: "profile", label: "Profile", testid: "tab-profile" },
  { id: "team", label: "Team", testid: "tab-team" },
  { id: "policy", label: "Policy & privileges", testid: "tab-policy" },
  { id: "coa", label: "Chart of accounts", testid: "tab-coa" },
] as const;

export function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab = TABS.find((t) => t.id === tabParam)?.id ?? "profile";
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(initialTab);
  const [saved, setSaved] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<string>(INDUSTRIES[1]);
  const [country, setCountry] = useState("AU");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [timezone, setTimezone] = useState("");
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);

  useEffect(() => {
    const next = TABS.find((t) => t.id === tabParam)?.id ?? "profile";
    setTab(next);
  }, [tabParam]);
  useEffect(() => {
    if (!user) return;
    setBusinessName(user.tenant_name);
    setEmail(user.email);
    setProfileLoading(true);
    api
      .getInstitutionSettings()
      .then((inst) => {
        setCountry(inst.country);
        setTimezone(inst.timezone);
      })
      .catch(() => {
        setCountry("AU");
        setTimezone(user.tenant_timezone);
      })
      .finally(() => setProfileLoading(false));
  }, [user]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 3000);
    return () => clearTimeout(t);
  }, [saved]);

  const countryMeta = countryByCode(country);

  const saveProfile = async () => {
    setProfileSaving(true);
    try {
      const inst = await api.updateInstitutionSettings({ country });
      setCountry(inst.country);
      setTimezone(inst.timezone);
      await refreshUser();
      setSaved(true);
    } catch {
      // keep form state; user can retry
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

      <PageHeader
        title="Settings"
        subtitle="Organisation profile, team, approval policy, and chart of accounts."
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

      {tab === "team" && <TenantMembersSection />}
      {tab === "policy" && <ApprovalPolicyPrivileges />}

      {tab === "coa" && (
        <Card className="overflow-hidden max-w-2xl">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="px-4 py-2 font-medium">Code</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-4 py-2 font-medium text-right">Type</th>
              </tr>
            </thead>
            <tbody>
              {CHART_OF_ACCOUNTS.map((row) => (
                <tr
                  key={row.code}
                  className="row-band border-b border-border/60 last:border-0"
                >
                  <td className="px-4 py-2.5 tnum text-muted-foreground">{row.code}</td>
                  <td className="px-3 py-2.5">{row.name}</td>
                  <td className="px-4 py-2.5 text-right">
                    <Badge variant="outline" className="text-[10px]">
                      {row.type}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
