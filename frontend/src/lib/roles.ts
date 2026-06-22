export const SUPER_ADMIN_ROLE = "super_admin";

export function isSuperAdmin(role: string | undefined | null): boolean {
  return role === SUPER_ADMIN_ROLE;
}

export function homePathForRole(role: string | undefined | null): string {
  return isSuperAdmin(role) ? "/platform/clients" : "/";
}
