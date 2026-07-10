import { Navigate, useLocation } from "react-router-dom";

/** Legacy route — customer setup lives in Creations → Customers. */
export function CustomersPage() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  if (!params.has("customersSection")) {
    params.set("customersSection", "capture");
  }
  if (!params.has("tab")) {
    params.set("tab", "customers");
  }
  return <Navigate to={`/creations?${params.toString()}`} replace />;
}
