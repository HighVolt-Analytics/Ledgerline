import { Navigate, useSearchParams } from "react-router-dom";

/** Legacy Finance route — bank feeds live under Upload → Bank feeds tab. */
export function BankFeedsPage() {
  const [searchParams] = useSearchParams();
  const account = searchParams.get("account");
  const qs = new URLSearchParams({ channel: "bank-feeds" });
  const tab = searchParams.get("bf_tab") ?? searchParams.get("tab");
  if (account) qs.set("account", account);
  if (tab) qs.set("bf_tab", tab);
  return <Navigate to={`/upload?${qs.toString()}`} replace />;
}
