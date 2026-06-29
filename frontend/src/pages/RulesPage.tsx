import { useEffect, useRef, useState } from "react";
import {
  Building2,
  CircleUser,
  Inbox,
  Layers,
  Loader2,
  Package,
  Receipt,
  Scale,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Card } from "@/components/ui/card";
import { DocumentTypesTab } from "@/components/rule-book/DocumentTypesTab";
import { AiClassificationSettingsPanel } from "@/components/rule-book/AiClassificationSettingsPanel";
import { IngestionTab } from "@/components/rule-book/IngestionTab";
import { EmployeesTab } from "@/components/rule-book/EmployeesTab";
import { ExpensesRulesTab } from "@/components/rule-book/ExpensesRulesTab";
import { LiveEvaluation } from "@/components/rule-book/LiveEvaluation";
import { RuleChangeHistory } from "@/components/rule-book/RuleChangeHistory";
import { DocumentSetsPanel } from "@/components/rule-book/DocumentSetsPanel";
import { PostingDefaultsPanel } from "@/components/rule-book/PostingDefaultsPanel";
import { PurchaseRulesTab } from "@/components/rule-book/PurchaseRulesTab";
import { PurchaseMatchSettingsPanel } from "@/components/rule-book/PurchaseMatchSettingsPanel";
import { TeamExpensesRulesTab } from "@/components/rule-book/TeamExpensesRulesTab";
import { VendorsTab } from "@/components/rule-book/VendorsTab";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useRuleBookConfig, useDeleteRuleBookDocumentType, useSaveRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRecognitionSignalCatalog } from "@/hooks/useRecognitionSignalCatalog";
import { useEmployeeMasters, useVendorMasters } from "@/hooks/useMasterData";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import { removeDocumentTypeFromCatalog } from "@/lib/documentTypeLifecycle";

const RULEBOOK_TABS = [
  { value: "ingestion", label: "Ingestion", testid: "tab-ingestion", icon: Inbox },
  { value: "document-types", label: "Document types", testid: "tab-document-types", icon: Layers },
  { value: "purchase", label: "Purchase GL", testid: "tab-purchase", icon: Package },
  { value: "expenses", label: "Expenses GL", testid: "tab-expenses", icon: Receipt },
  { value: "team", label: "Team GL", testid: "tab-team", icon: Users },
  { value: "vendors", label: "Vendors", testid: "tab-vendors", icon: Building2 },
  { value: "employees", label: "Employees", testid: "tab-employees", icon: CircleUser },
  { value: "posting", label: "Posting", testid: "tab-posting", icon: Scale },
] as const;

const SAVE_DEBOUNCE_MS = 800;

export function RulesPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<string>("ingestion");
  const [ruleBook, setRuleBook] = useState<RuleBookConfigState | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<RuleBookConfigState | null>(null);

  const tenantId = user?.tenant_id ?? null;
  const { data, isLoading, isError } = useRuleBookConfig(Boolean(user));
  useRecognitionSignalCatalog(Boolean(user));
  const { data: vendorMasters = [] } = useVendorMasters(Boolean(user));
  const { data: employeeMasters = [] } = useEmployeeMasters(Boolean(user));
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

  const flushSave = (next: RuleBookConfigState) => {
    pendingSaveRef.current = next;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState("pending");
    saveTimerRef.current = setTimeout(() => {
      const payload = pendingSaveRef.current;
      if (!payload) return;
      saveMutation.mutate(payload, {
        onSuccess: ({ config }) => {
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
      });
    }, SAVE_DEBOUNCE_MS);
  };

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  const canEdit = user?.role === "admin";

  const patch = (next: Partial<RuleBookConfigState>) => {
    if (!canEdit) return;
    setRuleBook((prev) => {
      if (!prev) return prev;
      const merged = { ...prev, ...next };
      flushSave(merged);
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

  if (isLoading || !ruleBook) {
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
    return <PageLoader />;
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
        subtitle="Configure ingestion, document types, GL rules, and posting."
        actions={saveStatus}
      />

      {!canEdit ? (
        <Card
          className="p-3 mb-5 border-amber-500/30 bg-amber-500/5 text-sm"
          data-testid="rulebook-readonly"
        >
          View-only mode — only organisation admins can edit rules, masters, and trigger remaps.
        </Card>
      ) : null}

      <PageTabs
        value={tab}
        onChange={setTab}
        variant="pill"
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
          onChange={(documentTypes) => patch({ documentTypes })}
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
      <PageTabPanel value="purchase" active={tab} className="mt-0 space-y-5">
        <PurchaseMatchSettingsPanel
          value={ruleBook.purchaseMatch}
          onChange={(purchaseMatch) => patch({ purchaseMatch })}
        />
        <PurchaseRulesTab
          rules={ruleBook.purchaseRules}
          onChange={(purchaseRules) => patch({ purchaseRules })}
        />
      </PageTabPanel>
      <PageTabPanel value="expenses" active={tab} className="mt-0">
        <ExpensesRulesTab
          rules={ruleBook.expenseRules}
          onChange={(expenseRules) => patch({ expenseRules })}
        />
      </PageTabPanel>
      <PageTabPanel value="team" active={tab} className="mt-0">
        <TeamExpensesRulesTab
          rules={ruleBook.teamExpenseRules}
          onChange={(teamExpenseRules) => patch({ teamExpenseRules })}
        />
      </PageTabPanel>
      <PageTabPanel value="vendors" active={tab} className="mt-0">
        <VendorsTab
          detection={ruleBook.vendorDetectionConfig}
          onDetectionChange={(vendorDetectionConfig) => patch({ vendorDetectionConfig })}
        />
      </PageTabPanel>
      <PageTabPanel value="employees" active={tab} className="mt-0">
        <EmployeesTab />
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
      </div>

      <RuleChangeHistory />

      <LiveEvaluation
        ruleBook={{
          ...ruleBook,
          vendorMasters: vendorMasters.length ? vendorMasters : ruleBook.vendorMasters,
          employeeMasters: employeeMasters.length ? employeeMasters : ruleBook.employeeMasters,
        }}
      />
    </div>
  );
}
