import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Inbox, Layers, Loader2, Scale } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Card } from "@/components/ui/card";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useRuleBookConfig, useDeleteRuleBookDocumentType, useSaveRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRecognitionSignalCatalog } from "@/hooks/useRecognitionSignalCatalog";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import { removeDocumentTypeFromCatalog } from "@/lib/documentTypeLifecycle";
import {
  mergeDocumentTypePatch,
  shouldApplyRuleBookSaveResponse,
} from "@/lib/ruleBookSave";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

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
const IngestionTab = lazy(() =>
  import("@/components/rule-book/IngestionTab").then((m) => ({
    default: m.IngestionTab,
  }))
);
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

const RULEBOOK_TABS = [
  { value: "ingestion", label: "Ingestion", testid: "tab-ingestion", icon: Inbox },
  { value: "document-types", label: "Document types", testid: "tab-document-types", icon: Layers },
  { value: "posting", label: "Posting", testid: "tab-posting", icon: Scale },
] as const;

const SAVE_DEBOUNCE_MS = 800;

export function RulesPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const [tab, setTab] = useState<string>(() => {
    if (tabFromUrl && RULEBOOK_TABS.some((row) => row.value === tabFromUrl)) {
      return tabFromUrl;
    }
    return "ingestion";
  });
  const [ruleBook, setRuleBook] = useState<RuleBookConfigState | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<RuleBookConfigState | null>(null);
  const executeSaveRef = useRef<() => void>(() => {});
  const saveGenerationRef = useRef(0);
  const saveInFlightRef = useRef(false);

  const tenantId = user?.tenant_id ?? null;
  const {
    data,
    isLoading,
    isError,
    blocked,
    refetch,
  } = useRuleBookConfig(Boolean(user));
  useRecognitionSignalCatalog(Boolean(user));
  const saveMutation = useSaveRuleBookConfig();
  const deleteDocumentTypeMutation = useDeleteRuleBookDocumentType();

  const cancelPendingSave = () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
  };

  useEffect(() => {
    hydratedRef.current = false;
    setRuleBook(null);
    cancelPendingSave();
    setSaveState("idle");
  }, [tenantId]);

  useEffect(() => {
    if (tabFromUrl && RULEBOOK_TABS.some((row) => row.value === tabFromUrl)) {
      setTab(tabFromUrl);
    }
  }, [tabFromUrl]);

  useEffect(() => {
    if (!data || hydratedRef.current) return;
    setRuleBook(data);
    hydratedRef.current = true;
  }, [data, tenantId]);

  useEffect(() => {
    if (!user) {
      hydratedRef.current = false;
      setRuleBook(null);
    }
  }, [user]);

  useEffect(() => {
    if (blocked && !isLoading) {
      void refetch();
    }
  }, [blocked, isLoading, refetch]);

  const runSave = () => {
    const payload = pendingSaveRef.current;
    if (!payload || saveInFlightRef.current) return;
    const generation = saveGenerationRef.current;
    saveInFlightRef.current = true;
    saveMutation.mutate(payload, {
      onSuccess: ({ config }) => {
        if (!shouldApplyRuleBookSaveResponse(generation, saveGenerationRef.current)) {
          return;
        }
        setRuleBook(config);
        setSaveState("saved");
      },
      onError: (err) => {
        setSaveState("error");
        toast({
          title: "Could not save rule book",
          description: err instanceof Error ? err.message : "Save failed",
          variant: "destructive",
        });
      },
      onSettled: () => {
        saveInFlightRef.current = false;
        if (saveGenerationRef.current > generation) {
          runSave();
        }
      },
    });
  };

  executeSaveRef.current = runSave;

  const flushSave = (next: RuleBookConfigState, options?: { immediate?: boolean }) => {
    pendingSaveRef.current = next;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState("pending");
    saveGenerationRef.current += 1;
    if (options?.immediate) {
      runSave();
      return;
    }
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      runSave();
    }, SAVE_DEBOUNCE_MS);
  };

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      if (pendingSaveRef.current) {
        executeSaveRef.current();
      }
    };
  }, []);

  const canEdit = user?.role === "admin";

  const patch = (next: Partial<RuleBookConfigState>, options?: { immediate?: boolean }) => {
    if (!canEdit) return;
    setRuleBook((prev) => {
      if (!prev) return prev;
      const merged = { ...prev, ...next };
      flushSave(merged, options);
      return merged;
    });
  };

  const patchDocumentType = (
    code: string,
    partial: Partial<DocumentTypeDefinition>,
    options?: { immediate?: boolean }
  ) => {
    if (!canEdit) return;
    setRuleBook((prev) => {
      if (!prev) return prev;
      const documentTypes = mergeDocumentTypePatch(prev.documentTypes, code, partial);
      const merged = { ...prev, documentTypes };
      flushSave(merged, options);
      return merged;
    });
  };

  if (!user) {
    return (
      <div>
        <PageHeader title="Rule Book" subtitle="Sign in to manage classification rules." />
      </div>
    );
  }

  const legacyCreationsTab =
    tabFromUrl === "vendors" || tabFromUrl === "customers" || tabFromUrl === "employees";
  if (legacyCreationsTab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tabFromUrl);
    return <Navigate to={`/creations?${params.toString()}`} replace />;
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

  const saveLabel =
    saveState === "pending" ||
    saveMutation.isPending ||
    deleteDocumentTypeMutation.isPending
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "error"
          ? "Save failed"
          : null;

  const saveStatus = saveLabel ? (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      data-testid="rulebook-save-status"
    >
      {(saveState === "pending" || saveMutation.isPending) && (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      )}
      {saveLabel}
    </span>
  ) : undefined;

  return (
    <div>
      <PageHeader
        title="Rule Book"
        subtitle="Configure ingestion, document types, Post to GL, and posting defaults."
        actions={saveStatus}
      />

      {!canEdit ? (
        <Card
          className="p-3 mb-5 ds-warning-panel border text-sm"
          data-testid="rulebook-readonly"
        >
          View-only mode — only organisation admins can edit rules, masters, and trigger remaps.
        </Card>
      ) : null}

      <PageTabs
        value={tab}
        onChange={setTab}
        className="mb-5 w-full"
        data-testid="rulebook-tabs"
        tabs={RULEBOOK_TABS.map((t) => {
          const Icon = t.icon;
          return {
            value: t.value,
            testid: t.testid,
            label: (
              <>
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {t.label}
              </>
            ),
          };
        })}
      />

      <div className={!canEdit ? "pointer-events-none opacity-90" : undefined}>
      <Suspense fallback={<PageLoader variant="rules" />}>
      <PageTabPanel value="document-types" active={tab} className="mt-0">
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
          onDeleteType={(code) => {
            if (!canEdit) return;
            cancelPendingSave();
            setRuleBook((prev) => (prev ? removeDocumentTypeFromCatalog(prev, code) : prev));
            deleteDocumentTypeMutation.mutate(code, {
              onSuccess: (config) => {
                setRuleBook(config);
                setSaveState("saved");
                toast({ title: "Document type deleted" });
              },
              onError: (err) => {
                if (data) setRuleBook(data);
                setSaveState("error");
                toast({
                  title: "Could not delete document type",
                  description: err instanceof Error ? err.message : "Delete failed",
                  variant: "destructive",
                });
              },
            });
          }}
          canEdit={canEdit}
        />
      </PageTabPanel>

      <PageTabPanel value="ingestion" active={tab} className="mt-0">
        <IngestionTab
          rules={ruleBook.emailCaptureRules}
          onChange={(emailCaptureRules) => patch({ emailCaptureRules })}
        />
      </PageTabPanel>
      <PageTabPanel value="posting" active={tab} className="mt-0 space-y-5">
        <PostingDefaultsPanel
          defaults={ruleBook.postingDefaults}
          onChange={(postingDefaults) => patch({ postingDefaults })}
        />
        <DocumentSetsPanel
          sets={ruleBook.documentSets}
          onChange={(documentSets) => patch({ documentSets })}
        />
      </PageTabPanel>
      </Suspense>
      </div>
    </div>
  );
}
