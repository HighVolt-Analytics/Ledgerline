import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { JournalExportTab } from "@/components/ledger-link/JournalExportTab";
import { LedgerExportTable } from "@/components/ledger-link/LedgerExportTable";
import { LedgerOverview } from "@/components/ledger-link/LedgerOverview";
import {
  LEDGER_BILLS,
  LEDGER_EXPENSES,
  LEDGER_INVOICES,
  LEDGER_PAYMENTS,
  LEDGER_PURCHASES,
} from "@/lib/v4MockData";

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

  return (
    <div>
      <PageHeader
        title="Ledger Link"
        subtitle="Reconcile double-entry postings, then export or push to your accounting system."
      />

      <PageTabs value={tab} onChange={setTab} className="flex-wrap h-auto" tabs={LL_TABS} />

      <PageTabPanel value="overview" active={tab} className="mt-4">
        <LedgerOverview />
      </PageTabPanel>
      <PageTabPanel value="invoices" active={tab} className="mt-4">
        <LedgerExportTable title="Invoices" rows={LEDGER_INVOICES} />
      </PageTabPanel>
      <PageTabPanel value="bills" active={tab} className="mt-4">
        <LedgerExportTable title="Bills" rows={LEDGER_BILLS} />
      </PageTabPanel>
      <PageTabPanel value="expenses" active={tab} className="mt-4">
        <LedgerExportTable title="Expenses" rows={LEDGER_EXPENSES} />
      </PageTabPanel>
      <PageTabPanel value="purchases" active={tab} className="mt-4">
        <LedgerExportTable title="Purchases" rows={LEDGER_PURCHASES} />
      </PageTabPanel>
      <PageTabPanel value="payments" active={tab} className="mt-4">
        <LedgerExportTable title="Payments" rows={LEDGER_PAYMENTS} />
      </PageTabPanel>
      <PageTabPanel value="export" active={tab} className="mt-4">
        <JournalExportTab />
      </PageTabPanel>
    </div>
  );
}
