import { useAuth } from "@/context/AuthContext";
import {
  DEFAULT_TENANT_LOCALE,
  DEFAULT_TENANT_TIMEZONE,
} from "@/lib/tenantTime";

/** Institution timezone/locale from the signed-in tenant (via /auth/me). */
export function useTenantTime() {
  const { user } = useAuth();
  return {
    timeZone: user?.tenant_timezone ?? DEFAULT_TENANT_TIMEZONE,
    locale: user?.tenant_locale ?? DEFAULT_TENANT_LOCALE,
  };
}
