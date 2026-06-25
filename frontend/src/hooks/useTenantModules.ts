import { usePermissions } from "@/hooks/usePermissions";

export function useTenantModules(): Record<string, boolean> | null {
  const { permissions } = usePermissions();
  return permissions?.enabled_modules ?? null;
}

export function useModuleEnabled(moduleKey: string): boolean {
  const modules = useTenantModules();
  if (!modules) return true;
  return modules[moduleKey] !== false;
}
