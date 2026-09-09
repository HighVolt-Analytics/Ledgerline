export const TENANT_ROLES = [
  "employee",
  "manager",
  "department_head",
  "finance_manager",
  "cfo",
  "director",
  "admin",
] as const;

export type TenantRoleSlug = (typeof TENANT_ROLES)[number];

const LABELS: Record<TenantRoleSlug, string> = {
  employee: "Employee",
  manager: "Manager",
  department_head: "Department Head",
  finance_manager: "Finance Manager",
  cfo: "CFO",
  director: "Director",
  admin: "Admin",
};

const LEGACY: Record<string, TenantRoleSlug> = {
  user: "employee",
  functional_manager: "manager",
  functional_supervisor: "department_head",
  finance_head: "finance_manager",
  bookkeeper: "cfo",
  auditor: "director",
  member: "manager",
  approver: "manager",
  viewer: "employee",
};

export function normalizeTenantRoleSlug(raw: string | undefined | null): TenantRoleSlug {
  const slug = (raw ?? "").trim().toLowerCase();
  if (slug in LABELS) return slug as TenantRoleSlug;
  if (slug in LEGACY) return LEGACY[slug];
  return "employee";
}

export function formatTenantRole(raw: string | undefined | null): string {
  return LABELS[normalizeTenantRoleSlug(raw)];
}

export const TENANT_ROLE_OPTIONS = TENANT_ROLES.map((value) => ({
  value,
  label: LABELS[value],
}));
