import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { buildLoginPathWithReturn } from "@/lib/authReturnTo";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  if (!user || user.id === 0) {
    const returnPath = `${location.pathname}${location.search}`;
    return <Navigate to={buildLoginPathWithReturn(returnPath)} replace />;
  }

  return <Outlet />;
}
