import { Navigate, useSearchParams } from "react-router-dom";

/** Legacy /rules URLs redirect to the current Rule Book and workspace locations. */
export function RulesPage() {
  const [searchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");

  if (tabFromUrl === "document-types") {
    return <Navigate to="/settings?tab=rule-book" replace />;
  }

  const legacyCreationsTab =
    tabFromUrl === "vendors" ||
    tabFromUrl === "customers" ||
    tabFromUrl === "employees";
  if (legacyCreationsTab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tabFromUrl);
    return <Navigate to={`/creations?${params.toString()}`} replace />;
  }

  if (tabFromUrl === "posting") {
    const params = new URLSearchParams(searchParams);
    params.set("tab", "posting");
    return <Navigate to={`/ledger-link?${params.toString()}`} replace />;
  }

  if (tabFromUrl === "ingestion") {
    return <Navigate to="/upload?channel=email&view=setup" replace />;
  }

  return <Navigate to="/settings?tab=rule-book" replace />;
}
