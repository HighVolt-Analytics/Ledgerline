export const TENANT_ROLES = [
  "admin",
  "functional_manager",
  "functional_supervisor",
  "finance_head",
  "bookkeeper",
  "auditor",
  "user",
] as const;

export type TenantRoleSlug = (typeof TENANT_ROLES)[number];

const LABELS: Record<TenantRoleSlug, string> = {
  admin: "Admin",
  functional_manager: "Functional manager",
  functional_supervisor: "Functional supervisor",
  finance_head: "Finance head",
  bookkeeper: "Bookkeeper",
  auditor: "Auditor",
  user: "User",
};

const LEGACY: Record<string, TenantRoleSlug> = {
  member: "functional_manager",
  approver: "functional_manager",
  viewer: "user",
};

export function normalizeTenantRoleSlug(raw: string | undefined | null): TenantRoleSlug {
  const slug = (raw ?? "").trim().toLowerCase();
  if (slug in LABELS) return slug as TenantRoleSlug;
  if (slug in LEGACY) return LEGACY[slug];
  return "user";
}

export function formatTenantRole(raw: string | undefined | null): string {
  return LABELS[normalizeTenantRoleSlug(raw)];
}

export const TENANT_ROLE_OPTIONS = TENANT_ROLES.map((value) => ({
  value,
  label: LABELS[value],
}));
