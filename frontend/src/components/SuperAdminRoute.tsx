import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { isSuperAdmin } from "@/lib/roles";

export function SuperAdminRoute() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  if (!user || !isSuperAdmin(user.role)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
