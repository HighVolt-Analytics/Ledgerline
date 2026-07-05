import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CollectionRow } from "@/components/collections/CollectionRow";
import { useCollectionMutations } from "@/hooks/useCollectionMutations";
import { useCollections } from "@/hooks/useCollections";
import { useTenantTime } from "@/hooks/useTenantTime";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { apiCollectionToRecord } from "@/lib/collectionsQueue";
import { money } from "@/lib/format";
import { collectionsKpis } from "@/lib/routePageAdapters";
import type { CollectionTab } from "@/lib/v4MockData";

const POLL_MS = 15_000;

const TABS: { value: CollectionTab; label: string; testid: string }[] = [
  { value: "queue", label: "Queue", testid: "tab-collections-queue" },
  { value: "awaiting", label: "Awaiting", testid: "tab-collections-awaiting" },
  { value: "received", label: "Received", testid: "tab-collections-received" },
  { value: "failed", label: "Failed", testid: "tab-collections-failed" },
];

export function CollectionsPage() {
  const { timeZone } = useTenantTime();
  const { data: collectionRows = [], isLoading, isError, refetch } = useCollections();
  const mutations = useCollectionMutations();
  const [tab, setTab] = useState<CollectionTab>("queue");
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);

  const collections = useMemo(() => collectionRows.map(apiCollectionToRecord), [collectionRows]);
  const kpis = collectionsKpis(collections, timeZone);
  const tabRows = useMemo(() => collections.filter((c) => c.tab === tab), [collections, tab]);

  useVisibilityPolling(() => {
    void refetch();
  }, POLL_MS);

  useEffect(() => {
    if (!mutations.toast) return;
    const t = setTimeout(() => mutations.setToast(null), 3000);
    return () => clearTimeout(t);
  }, [mutations.toast, mutations.setToast]);

  return (
    <div>
      {mutations.toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {mutations.toast}
        </div>
      )}

      <PageHeader
        title="Collections"
        subtitle="Accounts receivable — track customer invoices from three-way match through payment received."
      />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard label="Open receivables" value={isLoading ? "…" : kpis.count} testid="kpi-collections-open" />
        <KpiCard
          label="Outstanding"
          value={isLoading ? "…" : money(kpis.total)}
          testid="kpi-collections-total"
        />
        <KpiCard label="Overdue" value={isLoading ? "…" : kpis.overdue} testid="kpi-collections-overdue" />
        <KpiCard label="Due in 7 days" value={isLoading ? "…" : kpis.dueSoon} testid="kpi-collections-due-soon" />
      </div>

      <PageTabs
        value={tab}
        onChange={(v) => setTab(v as CollectionTab)}
        tabs={TABS.map((t) => ({
          value: t.value,
          label: t.label,
          testid: t.testid,
        }))}
      />

      <PageTabPanel value={tab} active={tab} className="mt-4 space-y-2">
        {isLoading ? (
          <div className="text-sm text-muted-foreground py-8">Loading collections…</div>
        ) : isError && !collectionsBlocked ? (
          <div className="text-sm text-destructive py-8">Could not load collections.</div>
        ) : tabRows.length === 0 ? (
          <EmptyState
            title={`No ${tab} collections`}
            hint={
              tab === "queue"
                ? "Invoices that pass sales three-way match appear here when due for collection."
                : "Nothing in this tab right now."
            }
          />
        ) : (
          tabRows.map((row) => (
            <CollectionRow
              key={row.id}
              row={row}
              busy={mutations.busyId === Number(row.id)}
              onOpenInvoice={() => setDrawerInvoiceId(Number(row.invoiceId))}
              onMarkReceived={
                tab === "queue" || tab === "awaiting"
                  ? () => void mutations.markReceived(Number(row.id))
                  : undefined
              }
            />
          ))
        )}
      </PageTabPanel>

      <InvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => void refetch()}
      />
    </div>
  );
}
