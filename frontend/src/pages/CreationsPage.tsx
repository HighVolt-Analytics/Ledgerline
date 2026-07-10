import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Building2, CircleUser, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import {
  CreationsEmployeesTabSkeleton,
  CreationsVendorsTabSkeleton,
} from "@/components/skeleton/PageSkeletons";
import { Card } from "@/components/ui/card";
import { CustomersTab } from "@/components/rule-book/CustomersTab";
import { EmployeesTab } from "@/components/rule-book/EmployeesTab";
import { VendorsTab } from "@/components/rule-book/VendorsTab";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useRuleBookConfig, useSaveRuleBookConfig } from "@/hooks/useRuleBookConfig";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import { shouldApplyRuleBookSaveResponse } from "@/lib/ruleBookSave";

const CREATIONS_TABS = [
  { value: "vendors", label: "Vendors", testid: "tab-vendors", icon: Building2 },
  { value: "customers", label: "Customers", testid: "tab-customers", icon: Building2 },
  { value: "employees", label: "Employees", testid: "tab-employees", icon: CircleUser },
] as const;

const SAVE_DEBOUNCE_MS = 800;

export function CreationsPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [searchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const customersSection = searchParams.get("customersSection");
  const mastersQ = searchParams.get("mastersQ");
  const [tab, setTab] = useState<string>(() => {
    if (tabFromUrl && CREATIONS_TABS.some((row) => row.value === tabFromUrl)) {
      return tabFromUrl;
    }
    return "vendors";
  });
  const [ruleBook, setRuleBook] = useState<RuleBookConfigState | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<RuleBookConfigState | null>(null);
  const executeSaveRef = useRef<() => void>(() => {});
  const saveGenerationRef = useRef(0);

  const tenantId = user?.tenant_id ?? null;
  const { data, isLoading, isError, blocked, refetch } = useRuleBookConfig(Boolean(user));
  const saveMutation = useSaveRuleBookConfig();

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
    if (tabFromUrl && CREATIONS_TABS.some((row) => row.value === tabFromUrl)) {
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
    if (!payload) return;
    saveGenerationRef.current += 1;
    const generation = saveGenerationRef.current;
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
          title: "Could not save vendor settings",
          description: err instanceof Error ? err.message : "Save failed",
          variant: "destructive",
        });
      },
    });
  };

  executeSaveRef.current = runSave;

  const flushSave = (next: RuleBookConfigState, options?: { immediate?: boolean }) => {
    pendingSaveRef.current = next;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState("pending");
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

  if (!user) {
    return (
      <div>
        <PageHeader title="Creations" subtitle="Sign in to manage vendors, customers, and employees." />
      </div>
    );
  }

  if (isError && !isLoading && !blocked) {
    return (
      <div>
        <PageHeader title="Creations" subtitle="Could not load master data configuration." />
        <Card className="p-6 text-sm text-muted-foreground">
          Failed to load from the server. Check that the API is running and try again.
        </Card>
      </div>
    );
  }

  const shellLoading = isLoading || blocked || !ruleBook;

  const saveLabel =
    saveState === "pending" || saveMutation.isPending
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "error"
          ? "Save failed"
          : null;

  const saveStatus =
    tab === "vendors" && saveLabel ? (
      <span
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
        data-testid="creations-save-status"
      >
        {saveState === "pending" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {saveLabel}
      </span>
    ) : undefined;

  return (
    <div>
      <PageHeader
        title="Creations"
        subtitle="Manage vendors, customers, and employees."
        actions={saveStatus}
      />

      {!canEdit ? (
        <Card
          className="p-3 mb-5 ds-warning-panel border text-sm"
          data-testid="creations-readonly"
        >
          View-only mode — only organisation admins can edit masters and vendor detection settings.
        </Card>
      ) : null}

      <PageTabs
        value={tab}
        onChange={setTab}
        className="mb-5 w-full"
        data-testid="creations-tabs"
        tabs={CREATIONS_TABS.map((t) => {
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
        {shellLoading ? (
          tab === "employees" ? (
            <CreationsEmployeesTabSkeleton />
          ) : tab === "vendors" ? (
            <CreationsVendorsTabSkeleton />
          ) : (
            <CustomersTab defaultSection={customersSection} />
          )
        ) : (
          <>
            <PageTabPanel value="vendors" active={tab} className="mt-0">
              <VendorsTab
                detection={ruleBook.vendorDetectionConfig}
                onDetectionChange={(vendorDetectionConfig) => patch({ vendorDetectionConfig })}
                initialSearchQuery={tab === "vendors" ? mastersQ : null}
              />
            </PageTabPanel>
            <PageTabPanel value="customers" active={tab} className="mt-0">
              <CustomersTab defaultSection={customersSection} />
            </PageTabPanel>
            <PageTabPanel value="employees" active={tab} className="mt-0">
              <EmployeesTab />
            </PageTabPanel>
          </>
        )}
      </div>
    </div>
  );
}
