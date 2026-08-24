import { Suspense, lazy } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/context/AuthContext";
import { useRuleBookIngestStats } from "@/hooks/useRuleBookConfig";
import { useRuleBookDraft } from "@/hooks/useRuleBookDraft";

const IngestionTab = lazy(() =>
  import("@/components/rule-book/IngestionTab").then((m) => ({
    default: m.IngestionTab,
  }))
);

export function RulesPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const {
    ruleBook,
    isLoading,
    isError,
    blocked,
    canEdit,
    saveLabel,
    isSaving,
    patch,
  } = useRuleBookDraft(Boolean(user));
  const { data: ingestStats } = useRuleBookIngestStats(Boolean(user));

  if (!user) {
    return (
      <div>
        <PageHeader title="Rule Book" subtitle="Sign in to manage capture and classification rules." />
      </div>
    );
  }

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

  if (isLoading || blocked || !ruleBook) {
    if (isError) {
      return (
        <div>
          <PageHeader title="Rule Book" subtitle="Could not load rule book configuration." />
          <Card className="p-6 text-sm text-muted-foreground">
            Failed to load from the server. Check that the API is running and try again.
          </Card>
        </div>
      );
    }
    return <PageLoader variant="rules" />;
  }

  const ingestionRules = ingestStats
    ? ruleBook.emailCaptureRules.map((rule) => {
        const row = ingestStats[rule.id];
        if (!row) return rule;
        return {
          ...rule,
          matchedCount: row.matched_count,
          lastMatched: row.last_matched,
        };
      })
    : ruleBook.emailCaptureRules;

  return (
    <div>
      <PageHeader
        title="Rule Book"
        subtitle="Configure how incoming mail and files are captured."
        actions={
          saveLabel ? (
            <span
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
              data-testid="rulebook-save-status"
            >
              {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {saveLabel}
            </span>
          ) : undefined
        }
      />

      {!canEdit ? (
        <Card
          className="p-3 mb-5 ds-warning-panel border text-sm"
          data-testid="rulebook-readonly"
        >
          View-only mode — only organisation admins can edit capture rules.
        </Card>
      ) : null}

      <div
        className={!canEdit ? "pointer-events-none opacity-90" : undefined}
        data-testid="tab-ingestion"
      >
        <Suspense fallback={<PageLoader variant="rules" />}>
          <IngestionTab
            rules={ingestionRules}
            onChange={(emailCaptureRules) => patch({ emailCaptureRules })}
          />
        </Suspense>
      </div>
    </div>
  );
}
