export const SETTINGS_TABS = [
  { id: "profile", label: "Profile", testid: "tab-profile" },
  { id: "ai-documents", label: "AI & documents", testid: "tab-ai-documents" },
  { id: "team", label: "Team", testid: "tab-team" },
  { id: "policy", label: "Policy & privileges", testid: "tab-policy" },
  { id: "coa", label: "Chart of accounts", testid: "tab-coa" },
] as const;

export type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];
