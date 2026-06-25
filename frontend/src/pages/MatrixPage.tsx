import { Navigate } from "react-router-dom";

/** Document Matrix now lives inside the Upload workspace. */
export function MatrixPage() {
  return <Navigate to="/upload?tab=matrix" replace />;
}
