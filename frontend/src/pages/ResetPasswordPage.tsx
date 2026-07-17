import { Navigate, useNavigate } from "react-router-dom";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";

/** Legacy email-link route — password reset now uses OTP on /forgot-password. */
export function ResetPasswordPage() {
  const navigate = useNavigate();

  // Keep legacy redirects aligned if tenant scope changes while this route is mounted.
  useResetOnTenantChange(() => {
    navigate("/forgot-password", { replace: true });
  });

  return <Navigate to="/forgot-password" replace />;
}
