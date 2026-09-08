import { useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Building2, CircleUser, CloudDownload, Landmark, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Card } from "@/components/ui/card";
import { PulledContactsPanel } from "@/components/contacts/PulledContactsPanel";
import { BanksTab } from "@/components/rule-book/BanksTab";
import { CustomersTab } from "@/components/rule-book/CustomersTab";
import { EmployeesTab } from "@/components/rule-book/EmployeesTab";
import { VendorsTab } from "@/components/rule-book/VendorsTab";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useModuleEnabled } from "@/hooks/useTenantModules";
import {
  useRuleBookVendorDetection,
  useSaveRuleBookVendorDetection,
} from "@/hooks/useRuleBookConfig";
import {
  DEFAULT_VENDOR_DETECTION_CONFIG,
  type VendorDetectionConfig,
} from "@/lib/v4RuleBookTypes";

const BASE_CREATIONS_TABS = [
  { value: "vendors", label: "Vendors", testid: "tab-vendors", icon: Building2 },
  { value: "customers", label: "Customers", testid: "tab-customers", icon: Building2 },
  { value: "pulled", label: "Pulled", testid: "tab-pulled", icon: CloudDownload },
  { value: "employees", label: "Employees", testid: "tab-employees", icon: CircleUser },
] as const;

const BANKS_TAB = {
  value: "banks",
  label: "Banks",
  testid: "tab-banks",
  icon: Landmark,
} as const;

const SAVE_DEBOUNCE_MS = 800;

export function CreationsPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const bankFeedsEnabled = useModuleEnabled("bank_feeds");
  const CREATIONS_TABS = useMemo(
    () => (bankFeedsEnabled ? [...BASE_CREATIONS_TABS, BANKS_TAB] : [...BASE_CREATIONS_TABS]),
    [bankFeedsEnabled]
  );
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
  const [detectionDraft, setDetectionDraft] = useState<VendorDetectionConfig | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<VendorDetectionConfig | null>(null);
  const executeSaveRef = useRef<() => void>(() => {});
  const saveGenerationRef = useRef(0);

  const {
    data: detectionFromServer,
    isError,
    blocked,
    refetch,
  } = useRuleBookVendorDetection(Boolean(user) && tab === "vendors");
  const saveMutation = useSaveRuleBookVendorDetection();
  const detection = detectionDraft ?? detectionFromServer ?? DEFAULT_VENDOR_DETECTION_CONFIG;

  const cancelPendingSave = () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
  };

  useEffect(() => {
    setDetectionDraft(null);
    cancelPendingSave();
    setSaveState("idle");
  }, [user?.tenant_id]);

  useEffect(() => {
    if (tabFromUrl && CREATIONS_TABS.some((row) => row.value === tabFromUrl)) {
      setTab(tabFromUrl);
    } else if (tabFromUrl === "banks" && !bankFeedsEnabled) {
      setTab("vendors");
    }
  }, [tabFromUrl, CREATIONS_TABS, bankFeedsEnabled]);

  useEffect(() => {
    if (tab === "banks" && !bankFeedsEnabled) {
      setTab("vendors");
    }
  }, [tab, bankFeedsEnabled]);

  useEffect(() => {
    if (blocked) {
      void refetch();
    }
  }, [blocked, refetch]);

  const runSave = () => {
    const payload = pendingSaveRef.current;
    if (!payload) return;
    saveGenerationRef.current += 1;
    const generation = saveGenerationRef.current;
    saveMutation.mutate(payload, {
      onSuccess: (config) => {
        if (generation !== saveGenerationRef.current) return;
        setDetectionDraft(config);
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

  const flushSave = (next: VendorDetectionConfig, options?: { immediate?: boolean }) => {
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

  const patchDetection = (
    next: VendorDetectionConfig,
    options?: { immediate?: boolean }
  ) => {
    if (!canEdit) return;
    setDetectionDraft(next);
    flushSave(next, options);
  };

  if (tabFromUrl === "document-types") {
    return <Navigate to="/settings?tab=rule-book" replace />;
  }

  if (!user) {
    return (
      <div>
        <PageHeader title="Contacts" subtitle="Sign in to manage vendors, customers, and employees." />
      </div>
    );
  }

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
    <div className="contacts-page">
      <PageHeader
        title="Contacts"
        actions={saveStatus}
      >
        <PageTabs
          value={tab}
          onChange={setTab}
          className="w-full"
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
      </PageHeader>

      {isError && tab === "vendors" ? (
        <Card className="p-3 mb-5 text-sm text-muted-foreground">
          Could not load vendor detection settings. Master list is still available.
        </Card>
      ) : null}

      {!canEdit ? (
        <Card
          className="p-3 mb-5 ds-warning-panel border text-sm"
          data-testid="creations-readonly"
        >
          View-only mode — only organisation admins can edit masters and vendor detection settings.
        </Card>
      ) : null}

      <div className={!canEdit ? "pointer-events-none opacity-90" : undefined}>
        <PageTabPanel value="vendors" active={tab} className="mt-0">
          <VendorsTab
            detection={detection}
            onDetectionChange={(vendorDetectionConfig) => patchDetection(vendorDetectionConfig)}
            initialSearchQuery={tab === "vendors" ? mastersQ : null}
          />
        </PageTabPanel>
        <PageTabPanel value="customers" active={tab} className="mt-0">
          <CustomersTab
            defaultSection={mastersQ ? "masters" : customersSection}
          />
        </PageTabPanel>
        <PageTabPanel value="pulled" active={tab} className="mt-0">
          <PulledContactsPanel canEdit={canEdit} />
        </PageTabPanel>
        <PageTabPanel value="employees" active={tab} className="mt-0">
          <EmployeesTab initialSearchQuery={tab === "employees" ? mastersQ : null} />
        </PageTabPanel>
        {bankFeedsEnabled ? (
          <PageTabPanel value="banks" active={tab} className="mt-0">
            <BanksTab canEdit={canEdit} />
          </PageTabPanel>
        ) : null}
      </div>
    </div>
  );
}
