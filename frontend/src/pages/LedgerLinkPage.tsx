import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { JournalExportTab } from "@/components/ledger-link/JournalExportTab";
import { LedgerExportTable } from "@/components/ledger-link/LedgerExportTable";
import { LedgerOverview } from "@/components/ledger-link/LedgerOverview";
import { PageLoader } from "@/components/PageLoader";
import { RuleBookPostingSection } from "@/components/rule-book/RuleBookPostingSection";
import { useAuth } from "@/context/AuthContext";
import { useLedgerLink, useLedgerLinkExports } from "@/hooks/useLedgerLink";
import { mapReconciliationOverview } from "@/lib/reconciliation";

const LL_TABS = [
  { value: "overview", label: "Overview", testid: "tab-ll-overview" },
  { value: "invoices", label: "Invoices", testid: "tab-ll-invoices" },
  { value: "bills", label: "Bills", testid: "tab-ll-bills" },
  { value: "expenses", label: "Expenses", testid: "tab-ll-expenses" },
  { value: "purchases", label: "Purchases", testid: "tab-ll-purchases" },
  { value: "payments", label: "Payments", testid: "tab-ll-payments" },
  { value: "export", label: "Journal Export", testid: "tab-ll-export" },
  { value: "posting", label: "Posting", testid: "tab-posting" },
];

export function LedgerLinkPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const [tab, setTab] = useState(() =>
    tabFromUrl && LL_TABS.some((row) => row.value === tabFromUrl) ? tabFromUrl : "overview"
  );
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const { user } = useAuth();
  const { data, isLoading, error } = useLedgerLink(Boolean(user) && tab !== "posting");
  const exportsEnabled = Boolean(user) && tab !== "overview" && tab !== "posting";
  const {
    data: exports,
    isLoading: exportsLoading,
    error: exportsError,
  } = useLedgerLinkExports(exportsEnabled);

  const recon = useMemo(
    () => (data?.overview ? mapReconciliationOverview(data.overview) : null),
    [data?.overview]
  );
  const currency = data?.overview.base_currency ?? "";
  const postingOnly = tab === "posting";

  useEffect(() => {
    if (tabFromUrl && LL_TABS.some((row) => row.value === tabFromUrl)) {
      setTab(tabFromUrl);
    }
  }, [tabFromUrl]);

  const changeTab = (next: string) => {
    setTab(next);
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  if (!user) {
    return (
      <div>
        <PageHeader
          title="Accounting"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <p className="text-sm text-muted-foreground">Sign in to view accounting data.</p>
      </div>
    );
  }

  if (!postingOnly && isLoading && !data) {
    return (
      <div>
        <PageHeader
          title="Accounting"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <PageLoader variant="table" />
      </div>
    );
  }

  if (!postingOnly && error) {
    return (
      <div>
        <PageHeader
          title="Accounting"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load accounting data"}
        </p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Accounting"
        subtitle="Reconcile double-entry postings, then export or push to your accounting system."
      >
        <PageTabs value={tab} onChange={changeTab} className="flex-wrap h-auto" tabs={LL_TABS} />
      </PageHeader>

      <PageTabPanel value="overview" active={tab} className="mt-4">
        <LedgerOverview
          recon={recon}
          loading={isLoading}
          currency={currency}
          onViewInvoice={setDrawerInvoiceId}
        />
      </PageTabPanel>
      <PageTabPanel value="invoices" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : exportsError ? (
          <p className="text-sm text-destructive">Could not load invoice exports.</p>
        ) : (
          <LedgerExportTable
            title="Invoices"
            rows={exports?.invoices ?? []}
            currency={currency}
            meta={exports?.group_meta?.invoices}
          />
        )}
      </PageTabPanel>
      <PageTabPanel value="bills" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : (
          <LedgerExportTable
            title="Bills"
            rows={exports?.bills ?? []}
            currency={currency}
            meta={exports?.group_meta?.bills}
          />
        )}
      </PageTabPanel>
      <PageTabPanel value="expenses" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : (
          <LedgerExportTable
            title="Expenses"
            rows={exports?.expenses ?? []}
            currency={currency}
            meta={exports?.group_meta?.expenses}
          />
        )}
      </PageTabPanel>
      <PageTabPanel value="purchases" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : (
          <LedgerExportTable
            title="Purchases"
            rows={exports?.purchases ?? []}
            currency={currency}
            meta={exports?.group_meta?.purchases}
          />
        )}
      </PageTabPanel>
      <PageTabPanel value="payments" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : (
          <LedgerExportTable
            title="Payments"
            rows={exports?.payments ?? []}
            currency={currency}
            meta={exports?.group_meta?.payments}
          />
        )}
      </PageTabPanel>
      <PageTabPanel value="export" active={tab} className="mt-4">
        {exportsLoading && !exports ? (
          <PageLoader variant="table" />
        ) : (
          <JournalExportTab exports={exports} currency={currency} />
        )}
      </PageTabPanel>
      <PageTabPanel value="posting" active={tab} className="mt-4">
        <RuleBookPostingSection />
      </PageTabPanel>

      <LazyInvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
      />
    </div>
  );
}
