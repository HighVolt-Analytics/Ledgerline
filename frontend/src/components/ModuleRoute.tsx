import { Navigate } from "react-router-dom";
import { useModuleEnabled } from "@/hooks/useTenantModules";

export function ModuleRoute({
  moduleKey,
  children,
}: {
  moduleKey: string;
  children: React.ReactNode;
}) {
  const enabled = useModuleEnabled(moduleKey);
  if (!enabled) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
