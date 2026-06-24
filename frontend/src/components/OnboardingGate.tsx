import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

/** Redirect tenant admins to onboarding until their organisation setup is complete. */
export function OnboardingGate() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  const needsOnboarding =
    user &&
    !user.is_support_session &&
    user.onboarding_completed === false &&
    (user.role === "admin" || user.role === "super_admin");

  if (needsOnboarding) {
    return <Navigate to="/onboarding" replace />;
  }

  return <Outlet />;
}
