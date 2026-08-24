import { Suspense, lazy } from "react";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageLoader } from "@/components/PageLoader";
import { useRuleBookDraft } from "@/hooks/useRuleBookDraft";

const DocumentSetsPanel = lazy(() =>
  import("@/components/rule-book/DocumentSetsPanel").then((m) => ({
    default: m.DocumentSetsPanel,
  }))
);
const PostingDefaultsPanel = lazy(() =>
  import("@/components/rule-book/PostingDefaultsPanel").then((m) => ({
    default: m.PostingDefaultsPanel,
  }))
);
const TeamExpensePostingPanel = lazy(() =>
  import("@/components/rule-book/TeamExpensePostingPanel").then((m) => ({
    default: m.TeamExpensePostingPanel,
  }))
);

export function RuleBookPostingSection() {
  const { ruleBook, isLoading, isError, blocked, canEdit, saveLabel, isSaving, patch } =
    useRuleBookDraft(true);

  if (isLoading || blocked || !ruleBook) {
    if (isError) {
      return (
        <Card className="p-6 text-sm text-muted-foreground">
          Could not load posting defaults. Check that the API is running and try again.
        </Card>
      );
    }
    return <PageLoader variant="rules" />;
  }

  return (
    <div className={!canEdit ? "pointer-events-none opacity-90" : undefined}>
      {saveLabel ? (
        <div className="mb-3 flex justify-end">
          <span
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
            data-testid="rulebook-save-status"
          >
            {isSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            {saveLabel}
          </span>
        </div>
      ) : null}
      <Suspense fallback={<PageLoader variant="rules" />}>
        <div className="space-y-5">
          <PostingDefaultsPanel
            defaults={ruleBook.postingDefaults}
            onChange={(postingDefaults) => patch({ postingDefaults })}
          />
          <TeamExpensePostingPanel
            defaults={ruleBook.teamExpensePosting}
            onChange={(teamExpensePosting) => patch({ teamExpensePosting })}
          />
          <DocumentSetsPanel
            sets={ruleBook.documentSets}
            onChange={(documentSets) => patch({ documentSets })}
          />
        </div>
      </Suspense>
    </div>
  );
}
