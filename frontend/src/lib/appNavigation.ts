import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  Coins,
  CreditCard,
  FolderKanban,
  LayoutDashboard,
  Link2,
  Plug,
  Receipt,
  Settings,
  ShoppingCart,
  TrendingUp,
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
    items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Workspace",
    items: [
      { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
      { to: "/dossiers", label: "Processing", icon: FolderKanban, moduleKey: "dossiers" },
      { to: "/creations", label: "Creations", icon: Users },
      { to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" },
      { to: "/rules", label: "Rule Book", icon: BookOpen, moduleKey: "rule_book" },
    ],
  },
  {
    label: "Reports",
    items: [{ to: "/reports", label: "Reports", icon: BarChart3, moduleKey: "reports" }],
  },
  {
    label: "Operations",
    items: [
      {
        to: "/team-expenses",
        label: "Team Expenses",
        icon: Receipt,
        badge: "team_expenses",
        moduleKey: "team_expenses",
      },
      {
        to: "/expenses",
        label: "Expenses Management",
        icon: Coins,
        badge: "business_expenses",
        moduleKey: "expenses",
      },
      {
        to: "/purchases",
        label: "Purchase Management",
        icon: ShoppingCart,
        moduleKey: "purchase",
      },
      {
        to: "/sales",
        label: "Sales Management",
        icon: TrendingUp,
        badge: "sales",
        moduleKey: "sales",
      },
    ],
  },
  {
    label: "Finance",
    items: [
      {
        to: "/collections",
        label: "Collections",
        icon: Coins,
        badge: "collections",
        moduleKey: "sales",
      },
      { to: "/ledger-link", label: "Accounting", icon: Link2, moduleKey: "ledger_link" },
      { to: "/payments", label: "Payments", icon: Wallet, badge: "payments", moduleKey: "payments" },
      { to: "/vault", label: "Vault", icon: Vault, moduleKey: "vault" },
    ],
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
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload", icon: Upload, badge: "upload" },
  { to: "/approvals", label: "Approvals", icon: CheckCircle2, badge: "approvals" },
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
