export const SETTINGS_TABS = [
  { id: "profile", label: "Profile", testid: "tab-profile" },
  { id: "ai-documents", label: "AI & documents", testid: "tab-ai-documents" },
  { id: "team", label: "Team", testid: "tab-team" },
  { id: "policy", label: "Policy & privileges", testid: "tab-policy" },
  { id: "coa", label: "Chart of accounts", testid: "tab-coa" },
  { id: "tax-rates", label: "Tax rates", testid: "tab-tax-rates" },
  { id: "rule-book", label: "Rule Book", testid: "tab-rule-book" },
] as const;

export type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];
