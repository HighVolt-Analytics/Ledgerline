import { useEffect, useMemo, useState } from "react";
import { Building2, Check, Plus } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import type { Organisation } from "@/api/types";
import { AddOrganisationDialog } from "@/components/AddOrganisationDialog";
import { ApprovalPolicyPrivileges } from "@/components/settings/ApprovalPolicyPrivileges";
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
  type TeamMemberRow,
} from "@/lib/settingsData";

const TABS = [
  { id: "profile", label: "Profile", testid: "tab-profile" },
  { id: "orgs", label: "Organisations", testid: "tab-orgs" },
  { id: "team", label: "Team", testid: "tab-team" },
  { id: "policy", label: "Policy & privileges", testid: "tab-policy" },
  { id: "coa", label: "Chart of accounts", testid: "tab-coa" },
] as const;

export function SettingsPage() {
  const { user, refreshUser, switchOrganisation } = useAuth();
  const [searchParams] = useSearchParams();
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [addOrgOpen, setAddOrgOpen] = useState(false);
  const [switchingOrgId, setSwitchingOrgId] = useState<number | null>(null);
  const tabParam = searchParams.get("tab");
  const initialTab = TABS.find((t) => t.id === tabParam)?.id ?? "profile";
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(initialTab);
  const [saved, setSaved] = useState(false);

  const [businessName, setBusinessName] = useState("");
  const [industry, setIndustry] = useState<string>(INDUSTRIES[1]);
  const [country, setCountry] = useState("AU");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  useEffect(() => {
    const next = TABS.find((t) => t.id === tabParam)?.id;
    if (next) setTab(next);
  }, [tabParam]);

  const loadOrganisations = () => {
    api.listOrganisations().then(setOrganisations).catch(() => undefined);
  };

  useEffect(() => {
    loadOrganisations();
  }, []);

  useEffect(() => {
    if (user) {
      setBusinessName(user.org_name);
      setEmail(user.email);
    }
  }, [user]);

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 3000);
    return () => clearTimeout(t);
  }, [saved]);

  const countryMeta = countryByCode(country);

  const orgRows = useMemo(() => {
    if (organisations.length) return organisations;
    if (!user) return [];
    return [
      {
        id: user.org_id,
        name: user.org_name,
        slug: user.org_slug,
        currency: countryMeta.currency,
        is_current: true,
      },
    ];
  }, [organisations, user, countryMeta.currency]);

  const teamMembers = useMemo<TeamMemberRow[]>(() => {
    if (!user) return [];
    return [
      {
        id: String(user.id),
        name: user.full_name,
        email: user.email,
        role: user.role,
      },
    ];
  }, [user]);

  const saveProfile = () => {
    setSaved(true);
  };

  const handleSwitchOrg = async (orgId: number) => {
    if (!user || orgId === user.org_id || switchingOrgId != null) return;
    setSwitchingOrgId(orgId);
    try {
      await switchOrganisation(orgId);
      await refreshUser();
      loadOrganisations();
      window.location.reload();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not switch organisation");
    } finally {
      setSwitchingOrgId(null);
    }
  };

  return (
    <div>
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
                onValueChange={setCountry}
                size="md"
                options={COUNTRIES.map((c) => ({ value: c.code, label: c.name }))}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground tnum">
                {countryMeta.currency} {countryMeta.symbol} · {countryMeta.taxLabel}{" "}
                {countryMeta.taxRate}%
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
            <Button data-testid="button-save-profile" onClick={saveProfile}>
              Save changes
            </Button>
          </div>
        </Card>
      )}

      {tab === "orgs" && (
        <Card className="p-4 max-w-2xl">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Your organisations</h3>
            <Button
              size="sm"
              data-testid="button-add-org"
              onClick={() => setAddOrgOpen(true)}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add organisation
            </Button>
          </div>
          <div className="space-y-2">
            {orgRows.map((org) => {
              const isActive = org.is_current;
              const orgEmail = isActive ? email : "—";
              const orgIndustry = isActive ? industry : "—";
              return (
                <div
                  key={org.id}
                  className="flex items-center gap-3 border-b border-border/60 pb-2.5 last:border-0 last:pb-0"
                  data-testid={`org-row-${org.id}`}
                >
                  <Building2 className="h-4 w-4 text-primary shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">{org.name}</div>
                    <div className="text-xs text-muted-foreground tnum truncate">
                      {org.currency} · {orgIndustry} · {orgEmail}
                    </div>
                  </div>
                  {isActive ? (
                    <Badge
                      variant="outline"
                      className="text-primary border-primary/40 shrink-0"
                    >
                      <Check className="h-3 w-3 mr-1" />
                      Active
                    </Badge>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs shrink-0"
                      data-testid={`button-switch-${org.id}`}
                      disabled={switchingOrgId != null}
                      onClick={() => void handleSwitchOrg(org.id)}
                    >
                      {switchingOrgId === org.id ? "Switching…" : "Switch"}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <AddOrganisationDialog
        open={addOrgOpen}
        onClose={() => setAddOrgOpen(false)}
        onCreated={() => {
          void refreshUser();
          loadOrganisations();
          window.location.reload();
        }}
      />

      {tab === "team" && (
        <Card className="overflow-hidden max-w-2xl">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-4 py-2 font-medium text-right">Role</th>
              </tr>
            </thead>
            <tbody>
              {teamMembers.map((member) => (
                <tr
                  key={member.id}
                  className="row-band border-b border-border/60 last:border-0"
                  data-testid={`user-${member.id}`}
                >
                  <td className="px-4 py-2.5 font-medium">{member.name}</td>
                  <td className="px-3 py-2.5 text-muted-foreground tnum text-xs">
                    {member.email}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <Badge variant="outline">{member.role}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

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
