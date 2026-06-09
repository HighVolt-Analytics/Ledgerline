import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Building2,
  CircleUser,
  Loader2,
  Mail,
  Package,
  Receipt,
  Scale,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Card } from "@/components/ui/card";
import { EmailCaptureTab } from "@/components/rule-book/EmailCaptureTab";
import { EmployeesTab } from "@/components/rule-book/EmployeesTab";
import { ExpensesRulesTab } from "@/components/rule-book/ExpensesRulesTab";
import { LiveEvaluation } from "@/components/rule-book/LiveEvaluation";
import { RuleChangeHistory } from "@/components/rule-book/RuleChangeHistory";
import { DocumentSetsPanel } from "@/components/rule-book/DocumentSetsPanel";
import { PostingDefaultsPanel } from "@/components/rule-book/PostingDefaultsPanel";
import { PurchaseRulesTab } from "@/components/rule-book/PurchaseRulesTab";
import { RoutingDiagram } from "@/components/rule-book/RoutingDiagram";
import { TeamExpensesRulesTab } from "@/components/rule-book/TeamExpensesRulesTab";
import { VendorsTab } from "@/components/rule-book/VendorsTab";
import { useToast } from "@/context/ToastContext";
import { useAuth } from "@/context/AuthContext";
import { useRuleBookConfig, useSaveRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useEmployeeMasters, useVendorMasters } from "@/hooks/useMasterData";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";

const RULEBOOK_TABS = [
  { value: "email", label: "Email Capture", testid: "tab-email", icon: Mail },
  { value: "purchase", label: "Purchase Mgmt", testid: "tab-purchase", icon: Package },
  { value: "expenses", label: "Expenses", testid: "tab-expenses", icon: Receipt },
  { value: "team", label: "Team Expenses", testid: "tab-team", icon: Users },
  { value: "vendors", label: "Vendors", testid: "tab-vendors", icon: Building2 },
  { value: "employees", label: "Employees", testid: "tab-employees", icon: CircleUser },
  { value: "posting", label: "Posting", testid: "tab-posting", icon: Scale },
] as const;

const SAVE_DEBOUNCE_MS = 800;

export function RulesPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<string>("email");
  const [ruleBook, setRuleBook] = useState<RuleBookConfigState | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saved" | "error">("idle");
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<RuleBookConfigState | null>(null);

  const { data, isLoading, isError } = useRuleBookConfig(Boolean(user));
  const { data: vendorMasters = [] } = useVendorMasters(Boolean(user));
  const { data: employeeMasters = [] } = useEmployeeMasters(Boolean(user));
  const saveMutation = useSaveRuleBookConfig();

  useEffect(() => {
    if (!data || hydratedRef.current) return;
    setRuleBook(data);
    hydratedRef.current = true;
  }, [data]);

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
        onSuccess: ({ remapped }) => {
          setSaveState("saved");
          if (remapped > 0) {
            toast({
              title: "Documents re-mapped",
              description: `${remapped} document${remapped === 1 ? "" : "s"} updated after rule change.`,
            });
          }
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
    saveState === "pending" || saveMutation.isPending
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "error"
          ? "Save failed"
          : null;

  return (
    <div>
      <PageHeader
        title="Rule Book"
        subtitle="Coordinated rule books that capture, classify, and code every document from inbox to ledger."
        actions={
          saveLabel ? (
            <span
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
              data-testid="rulebook-save-status"
            >
              {(saveState === "pending" || saveMutation.isPending) && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              )}
              {saveLabel}
            </span>
          ) : undefined
        }
      />

      <RoutingDiagram />

      <Card
        className="p-3 mb-5 bg-primary/5 border-primary/20 text-sm flex items-start gap-2"
        data-testid="rulebook-note"
      >
        <BookOpen className="h-4 w-4 text-primary mt-0.5 shrink-0" />
        <span>
          Email capture routes documents to the right workflow. Purchase, expense, and vendor rules
          classify GL accounts. Use the Posting tab for tax, payable, fallback, and vault document sets.
        </span>
      </Card>

      {!canEdit ? (
        <Card
          className="p-3 mb-5 border-amber-500/30 bg-amber-500/5 text-sm"
          data-testid="rulebook-readonly"
        >
          View-only mode — only organisation admins can edit rules, masters, and trigger remaps.
        </Card>
      ) : null}

      <div className={!canEdit ? "pointer-events-none opacity-90" : undefined}>
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

      <PageTabPanel value="email" active={tab} className="mt-0">
        <EmailCaptureTab
          rules={ruleBook.emailCaptureRules}
          onChange={(emailCaptureRules) => patch({ emailCaptureRules })}
        />
      </PageTabPanel>
      <PageTabPanel value="purchase" active={tab} className="mt-0">
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
