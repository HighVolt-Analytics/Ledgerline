import { Suspense, lazy } from "react";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageLoader } from "@/components/PageLoader";
import { useRecognitionSignalCatalog } from "@/hooks/useRecognitionSignalCatalog";
import { useRuleBookDraft } from "@/hooks/useRuleBookDraft";

const AiClassificationSettingsPanel = lazy(() =>
  import("@/components/rule-book/AiClassificationSettingsPanel").then((m) => ({
    default: m.AiClassificationSettingsPanel,
  }))
);
const DocumentTypesTab = lazy(() =>
  import("@/components/rule-book/DocumentTypesTab").then((m) => ({
    default: m.DocumentTypesTab,
  }))
);

export function RuleBookDocumentTypesSection() {
  const {
    ruleBook,
    isLoading,
    isError,
    blocked,
    canEdit,
    saveLabel,
    isSaving,
    patch,
    patchDocumentType,
    deleteDocumentType,
  } = useRuleBookDraft(true);
  useRecognitionSignalCatalog(Boolean(ruleBook));

  if (isLoading || blocked || !ruleBook) {
    if (isError) {
      return (
        <Card className="p-6 text-sm text-muted-foreground">
          Could not load document types. Check that the API is running and try again.
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
        <AiClassificationSettingsPanel
          value={
            ruleBook.aiClassification ?? {
              documentAiProvider: "azure_di",
              autoRouteMinConfidence: 0.85,
            }
          }
          onChange={(aiClassification) => patch({ aiClassification })}
          canEdit={canEdit}
        />
        <DocumentTypesTab
          documentTypes={ruleBook.documentTypes}
          onChange={(documentTypes, options) => patch({ documentTypes }, options)}
          onPatchDocumentType={patchDocumentType}
          onDeleteType={deleteDocumentType}
          canEdit={canEdit}
        />
      </Suspense>
    </div>
  );
}
