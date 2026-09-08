import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  ClipboardCheck,
  Coins,
  CreditCard,
  Gauge,
  Link2,
  Plug,
  Settings,
  Upload,
  Users,
  Vault,
  Wallet,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  badge?: "upload" | "approvals" | "team_expenses" | "business_expenses" | "sales" | "payments" | "collections";
  moduleKey?: string;
};

export type NavGroup = {
  label: string;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Dashboard",
    items: [{ to: "/", label: "Dashboard", icon: Gauge }],
  },
  {
    label: "Upload",
    items: [{ to: "/upload", label: "Upload", icon: Upload, badge: "upload" }],
  },
  {
    label: "Approvals",
    items: [{ to: "/approvals", label: "Approvals", icon: ClipboardCheck, badge: "approvals" }],
  },
  {
    label: "Cashflow",
    items: [
      {
        to: "/payments",
        label: "Payments",
        icon: Wallet,
        badge: "payments",
        moduleKey: "payments",
      },
      {
        to: "/collections",
        label: "Collections",
        icon: Coins,
        badge: "collections",
        moduleKey: "sales",
      },
    ],
  },
  {
    label: "Ledger Sync",
    items: [{ to: "/ledger-link", label: "Ledger Sync", icon: Link2, moduleKey: "ledger_link" }],
  },
  {
    label: "Vault",
    items: [{ to: "/vault", label: "Vault", icon: Vault, moduleKey: "vault" }],
  },
  {
    label: "Reports",
    items: [{ to: "/reports", label: "Reports", icon: BarChart3, moduleKey: "reports" }],
  },
  {
    label: "Contacts",
    items: [{ to: "/creations", label: "Contacts", icon: Users }],
  },
  {
    label: "Admin",
    items: [
      { to: "/integrations", label: "Integrations", icon: Plug },
      { to: "/billing", label: "Billing & Credits", icon: CreditCard },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export const MOBILE_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
  { to: "/approvals", label: "Approvals", icon: ClipboardCheck, badge: "approvals" },
  { to: "/creations", label: "Contacts", icon: Users },
  { to: "/settings", label: "Settings", icon: Settings },
];

export type FlatNavItem = NavItem & { group: string };

export function flattenNavItems(groups: readonly NavGroup[]): FlatNavItem[] {
  return groups.flatMap((group) =>
    group.items.map((item) => ({ ...item, group: group.label }))
  );
}

export function filterNavItems(items: FlatNavItem[], query: string): FlatNavItem[] {
  const token = query.trim().toLowerCase();
  if (!token) return items;
  return items.filter(
    (item) =>
      item.label.toLowerCase().includes(token) ||
      item.group.toLowerCase().includes(token) ||
      item.to.toLowerCase().includes(token)
  );
}
