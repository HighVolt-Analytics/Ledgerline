import { Suspense, lazy, useState } from "react";
import { Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageLoader } from "@/components/PageLoader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
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
const BankNarrationRulesTab = lazy(() =>
  import("@/components/rule-book/BankNarrationRulesTab").then((m) => ({
    default: m.BankNarrationRulesTab,
  }))
);

const RULE_BOOK_SUBTABS = [
  { value: "document-types", label: "Document types", testid: "rb-subtab-document-types" },
  { value: "bank-narration", label: "Bank narration", testid: "rb-subtab-bank-narration" },
] as const;

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
  const [subTab, setSubTab] = useState<(typeof RULE_BOOK_SUBTABS)[number]["value"]>(
    "document-types"
  );

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

      <PageTabs
        tabs={[...RULE_BOOK_SUBTABS]}
        value={subTab}
        onChange={(v) => setSubTab(v as (typeof RULE_BOOK_SUBTABS)[number]["value"])}
        className="mb-4"
        data-testid="rule-book-subtabs"
      />

      <PageTabPanel value="document-types" active={subTab}>
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
      </PageTabPanel>

      <PageTabPanel value="bank-narration" active={subTab}>
        <Suspense fallback={<PageLoader variant="rules" />}>
          <BankNarrationRulesTab
            rules={ruleBook.bankNarrationRules ?? []}
            onChange={(bankNarrationRules) => patch({ bankNarrationRules })}
            canEdit={canEdit}
          />
        </Suspense>
      </PageTabPanel>
    </div>
  );
}
