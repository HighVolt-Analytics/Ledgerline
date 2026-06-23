export const TENANT_ROLES = [
  "admin",
  "approver",
  "bookkeeper",
  "viewer",
  "auditor",
] as const;

export type TenantRoleSlug = (typeof TENANT_ROLES)[number];

const LABELS: Record<TenantRoleSlug, string> = {
  admin: "Admin",
  approver: "Approver",
  bookkeeper: "Bookkeeper",
  viewer: "Viewer",
  auditor: "Auditor",
};

const LEGACY: Record<string, TenantRoleSlug> = {
  member: "approver",
};

export function normalizeTenantRoleSlug(raw: string | undefined | null): TenantRoleSlug {
  const slug = (raw ?? "").trim().toLowerCase();
  if (slug in LABELS) return slug as TenantRoleSlug;
  if (slug in LEGACY) return LEGACY[slug];
  return "viewer";
}

export function formatTenantRole(raw: string | undefined | null): string {
  return LABELS[normalizeTenantRoleSlug(raw)];
}

export const TENANT_ROLE_OPTIONS = TENANT_ROLES.map((value) => ({
  value,
  label: LABELS[value],
}));
