import { Navigate, useSearchParams } from "react-router-dom";

/** Legacy Finance route — bank feeds live under Upload → Bank feeds tab. */
export function BankFeedsPage() {
  const [searchParams] = useSearchParams();
  const account = searchParams.get("account");
  const qs = new URLSearchParams({ channel: "bank-feeds" });
  if (account) qs.set("account", account);
  return <Navigate to={`/upload?${qs.toString()}`} replace />;
}
