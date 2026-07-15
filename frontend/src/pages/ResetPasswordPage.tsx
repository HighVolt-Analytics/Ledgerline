import { Navigate } from "react-router-dom";

/** Legacy email-link route — password reset now uses OTP on /forgot-password. */
export function ResetPasswordPage() {
  return <Navigate to="/forgot-password" replace />;
}
