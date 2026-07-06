import { useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { JournalExportTab } from "@/components/ledger-link/JournalExportTab";
import { LedgerExportTable } from "@/components/ledger-link/LedgerExportTable";
import { LedgerOverview } from "@/components/ledger-link/LedgerOverview";
import { PageLoader } from "@/components/PageLoader";
import { useAuth } from "@/context/AuthContext";
import { useLedgerLink } from "@/hooks/useLedgerLink";
import { mapReconciliationOverview } from "@/lib/reconciliation";

const LL_TABS = [
  { value: "overview", label: "Overview", testid: "tab-ll-overview" },
  { value: "invoices", label: "Invoices", testid: "tab-ll-invoices" },
  { value: "bills", label: "Bills", testid: "tab-ll-bills" },
  { value: "expenses", label: "Expenses", testid: "tab-ll-expenses" },
  { value: "purchases", label: "Purchases", testid: "tab-ll-purchases" },
  { value: "payments", label: "Payments", testid: "tab-ll-payments" },
  { value: "export", label: "Journal Export", testid: "tab-ll-export" },
];

export function LedgerLinkPage() {
  const [tab, setTab] = useState("overview");
  const { user } = useAuth();
  const { data, isLoading, error } = useLedgerLink(Boolean(user));

  const recon = useMemo(
    () => (data?.overview ? mapReconciliationOverview(data.overview) : null),
    [data?.overview]
  );
  const currency = data?.overview.base_currency ?? "AUD";
  const exports = data?.exports;

  if (!user) {
    return (
      <div>
        <PageHeader
          title="Ledger Link"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <p className="text-sm text-muted-foreground">Sign in to view ledger link data.</p>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div>
        <PageHeader
          title="Ledger Link"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <PageLoader variant="table" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader
          title="Ledger Link"
          subtitle="Reconcile double-entry postings, then export or push to your accounting system."
        />
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load ledger link"}
        </p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Ledger Link"
        subtitle="Reconcile double-entry postings, then export or push to your accounting system."
      >
        <PageTabs value={tab} onChange={setTab} className="flex-wrap h-auto" tabs={LL_TABS} />
      </PageHeader>

      <PageTabPanel value="overview" active={tab} className="mt-4">
        <LedgerOverview recon={recon} loading={isLoading} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="invoices" active={tab} className="mt-4">
        <LedgerExportTable title="Invoices" rows={exports?.invoices ?? []} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="bills" active={tab} className="mt-4">
        <LedgerExportTable title="Bills" rows={exports?.bills ?? []} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="expenses" active={tab} className="mt-4">
        <LedgerExportTable title="Expenses" rows={exports?.expenses ?? []} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="purchases" active={tab} className="mt-4">
        <LedgerExportTable title="Purchases" rows={exports?.purchases ?? []} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="payments" active={tab} className="mt-4">
        <LedgerExportTable title="Payments" rows={exports?.payments ?? []} currency={currency} />
      </PageTabPanel>
      <PageTabPanel value="export" active={tab} className="mt-4">
        <JournalExportTab exports={exports} currency={currency} />
      </PageTabPanel>
    </div>
  );
}
