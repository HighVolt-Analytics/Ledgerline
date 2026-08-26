import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { CollectionRow } from "@/components/collections/CollectionRow";
import { ListRowSkeleton } from "@/components/skeleton/PageSkeletons";
import { useCollectionMutations } from "@/hooks/useCollectionMutations";
import {
  COLLECTIONS_PAGE_SIZE,
  useCollectionWorkspaceKpis,
  useCollections,
} from "@/hooks/useCollections";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { apiCollectionToRecord } from "@/lib/collectionsQueue";
import { formatMoneyByCurrencyMap } from "@/lib/format";
import type { CollectionTab } from "@/lib/v4MockData";

const POLL_MS = 90_000;

const TABS: { value: CollectionTab; label: string; testid: string }[] = [
  { value: "queue", label: "Queue", testid: "tab-collections-queue" },
  { value: "awaiting", label: "Awaiting", testid: "tab-collections-awaiting" },
  { value: "received", label: "Received", testid: "tab-collections-received" },
  { value: "failed", label: "Failed", testid: "tab-collections-failed" },
];

function tabCountFromKpis(
  tab: CollectionTab,
  kpis: { queue_count: number; awaiting_count: number; received_count: number; failed_count: number } | undefined
): number | undefined {
  if (kpis == null) return undefined;
  if (tab === "queue") return kpis.queue_count;
  if (tab === "awaiting") return kpis.awaiting_count;
  if (tab === "received") return kpis.received_count;
  return kpis.failed_count;
}

export function CollectionsPage() {
  const [tab, setTab] = useState<CollectionTab>("queue");
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const {
    data: collectionRows = [],
    isLoading,
    isError,
    refetch,
    blocked: collectionsBlocked,
  } = useCollections(tab);
  const {
    data: kpis,
    isLoading: kpisLoading,
    refetch: refetchKpis,
  } = useCollectionWorkspaceKpis();
  const mutations = useCollectionMutations();

  const collections = useMemo(
    () => (collectionsBlocked ? [] : collectionRows).map(apiCollectionToRecord),
    [collectionRows, collectionsBlocked]
  );
  const tabCount = tabCountFromKpis(tab, kpis);
  const showKpiPlaceholder = kpisLoading || collectionsBlocked;

  useVisibilityPolling(() => {
    return Promise.all([refetch(), refetchKpis()]);
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
        <KpiCard
          label="Open receivables"
          value={showKpiPlaceholder ? "…" : (kpis?.open_count ?? 0)}
          testid="kpi-collections-open"
        />
        <KpiCard
          label="Outstanding"
          value={showKpiPlaceholder ? "…" : formatMoneyByCurrencyMap(kpis?.outstanding_by_currency ?? {})}
          testid="kpi-collections-total"
        />
        <KpiCard
          label="Overdue"
          value={showKpiPlaceholder ? "…" : (kpis?.overdue_count ?? 0)}
          testid="kpi-collections-overdue"
        />
        <KpiCard
          label="Due in 7 days"
          value={showKpiPlaceholder ? "…" : (kpis?.due_soon_count ?? 0)}
          testid="kpi-collections-due-soon"
        />
      </div>

      <PageTabs
        value={tab}
        onChange={(v) => setTab(v as CollectionTab)}
        tabs={TABS.map((t) => ({
          value: t.value,
          label: kpis == null ? t.label : `${t.label} (${tabCountFromKpis(t.value, kpis) ?? 0})`,
          testid: t.testid,
        }))}
      />

      <PageTabPanel value={tab} active={tab} className="mt-4 space-y-2">
        {isLoading || collectionsBlocked ? (
          <Card className="p-2 space-y-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <ListRowSkeleton key={i} actionWidth="w-20" />
            ))}
          </Card>
        ) : isError && !collectionsBlocked ? (
          <div className="text-sm text-destructive py-8">Could not load collections.</div>
        ) : collections.length === 0 ? (
          <EmptyState
            title={`No ${tab} collections`}
            hint={
              tab === "queue"
                ? "Invoices that pass sales three-way match appear here when due for collection."
                : "Nothing in this tab right now."
            }
          />
        ) : (
          <>
            {collections.map((row) => (
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
            ))}
            {tabCount != null && tabCount > collections.length ? (
              <p className="text-xs text-muted-foreground px-1 pt-1">
                Showing {collections.length} of {tabCount}
                {tabCount > COLLECTIONS_PAGE_SIZE ? ` (first ${COLLECTIONS_PAGE_SIZE})` : ""}.
              </p>
            ) : null}
          </>
        )}
      </PageTabPanel>

      <LazyInvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => {
          void refetch();
          void refetchKpis();
        }}
      />
    </div>
  );
}
