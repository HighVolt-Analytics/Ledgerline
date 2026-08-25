import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";

export function RulesPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
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

  if (!user) {
    return (
      <div>
        <PageHeader title="Rule Book" subtitle="Sign in to manage capture and classification rules." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Rule Book"
        subtitle="Document types live in Settings. Email ingestion is configured when you add a mailbox."
      />
      <Card className="p-5 space-y-3 max-w-xl" data-testid="tab-ingestion">
        <p className="text-sm text-muted-foreground">
          Ingestion rules are no longer edited here. Open Upload → Email and click Add mailbox —
          mailbox details stay at the top, and ingestion rules sit below.
        </p>
        <Button type="button" onClick={() => navigate("/upload?channel=email")}>
          Go to Email upload
        </Button>
      </Card>
    </div>
  );
}
