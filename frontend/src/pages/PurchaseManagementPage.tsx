import { useEffect, useMemo, useState } from "react";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { PurchaseCaptureStrip } from "@/components/purchases/PurchaseCaptureStrip";
import {
  PurchaseDetailContent,
  PurchaseDetailSheet,
} from "@/components/purchases/PurchaseDetailPanel";
import {
  PurchaseRegisterPanel,
  type PurchaseRegisterTab,
} from "@/components/purchases/PurchaseRegisterPanel";
import { usePurchaseMutations } from "@/hooks/usePurchaseMutations";
import { usePurchases, usePurchaseWorkspaceKpis } from "@/hooks/usePurchases";
import { useRuleBookPurchaseRules } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { purchaseActionRequiredInvoices } from "@/lib/purchaseRegisterQueue";
import {
  apiPurchaseToRow,
  isPurchaseTwoWayMode,
  purchaseKpisFromRegister,
  splitPurchaseRegisterRows,
} from "@/lib/routePageAdapters";

const ROUTE_TARGET = "Purchase Management";
const POLL_MS = 90_000;
const ACTION_PAGE_SIZE = 50;

function purchaseRowKey(purchaseId: number, invoiceId: number | null) {
  return `${purchaseId}-${invoiceId ?? "none"}`;
}

export function PurchaseManagementPage({ embedded = false }: { embedded?: boolean }) {
  const [registerTab, setRegisterTab] = useState<PurchaseRegisterTab>("register");
  const {
    data: purchaseRows = [],
    isLoading: purchasesLoading,
    isError,
    refetch: refetchPurchases,
  } = usePurchases();
  const { data: workspaceKpis, refetch: refetchKpis } = usePurchaseWorkspaceKpis();
  const { data: purchaseRules = [] } = useRuleBookPurchaseRules();
  const {
    data: routed = [],
    refetch: refetchRouted,
  } = useRoutedInvoices(ROUTE_TARGET, registerTab === "action", {
    pageSize: ACTION_PAGE_SIZE,
    maxPages: 1,
  });
  const mutations = usePurchaseMutations();

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const { threeWayApiRows, twoWayApiRows } = useMemo(() => {
    const split = splitPurchaseRegisterRows(purchaseRows);
    return { threeWayApiRows: split.threeWayRows, twoWayApiRows: split.twoWayRows };
  }, [purchaseRows]);
  const threeWayRows = useMemo(
    () => threeWayApiRows.map(apiPurchaseToRow),
    [threeWayApiRows]
  );
  const twoWayRows = useMemo(() => twoWayApiRows.map(apiPurchaseToRow), [twoWayApiRows]);
  const rows = threeWayRows;
  const actionRequired = useMemo(
    () => purchaseActionRequiredInvoices(routed, purchaseRows),
    [routed, purchaseRows]
  );
  const kpis = useMemo(() => {
    const fromRegister = purchaseKpisFromRegister(purchaseRows, routed);
    return {
      ...fromRegister,
      awaitingPo: workspaceKpis?.awaiting_po_count ?? fromRegister.awaitingPo,
      needsAction: workspaceKpis?.needs_action_count ?? fromRegister.needsAction,
    };
  }, [purchaseRows, routed, workspaceKpis]);
  const selected =
    rows.find((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey) ??
    twoWayRows.find((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey) ??
    null;
  const activeRuleCount = useMemo(
    () => purchaseRules.filter((r) => r.enabled).length,
    [purchaseRules]
  );

  const refetchAll = async () => {
    await Promise.all([
      refetchPurchases(),
      refetchKpis(),
      registerTab === "action" ? refetchRouted() : Promise.resolve(),
    ]);
  };

  useVisibilityPolling(() => {
    return refetchAll();
  }, POLL_MS);

  useEffect(() => {
    if (
      selectedKey &&
      !threeWayRows.some((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey) &&
      !twoWayRows.some((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey)
    ) {
      setSelectedKey(null);
    }
  }, [selectedKey, threeWayRows, twoWayRows]);

  useEffect(() => {
    if (!mutations.toast) return;
    const t = setTimeout(() => mutations.setToast(null), 3000);
    return () => clearTimeout(t);
  }, [mutations.toast, mutations.setToast]);

  const handleApproveVariance = async (purchaseId: number) => {
    await mutations.approveVariance(purchaseId);
  };

  const handleRecordGrn = async (
    purchaseId: number,
    body: { grn_qty: number; receiver?: string; condition_note?: string }
  ) => {
    await mutations.recordGrn(purchaseId, body);
  };

  return (
    <div>
      {mutations.toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {mutations.toast}
        </div>
      )}

      {embedded ? null : (
        <PageHeader
          title="Purchase Management"
          subtitle="PO → GRN → Invoice matching (3-way or 2-way per playbook). Variances are routed for tiered approval before payment."
        />
      )}

      <PurchaseCaptureStrip activeRuleCount={activeRuleCount} enabled={!purchasesLoading} />

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 mb-5">
        <KpiCard
          label="Open POs"
          value={purchasesLoading ? "…" : kpis.openPos}
          testid="kpi-po-open"
        />
        <KpiCard
          label="Awaiting PO"
          value={purchasesLoading ? "…" : kpis.awaitingPo}
          testid="kpi-po-awaiting"
          onClick={kpis.awaitingPo > 0 ? () => setRegisterTab("action") : undefined}
          delta={
            !purchasesLoading && kpis.awaitingPo > 0
              ? { dir: "down", text: "invoice before PO", good: false }
              : undefined
          }
        />
        <KpiCard
          label="Pending GRN"
          value={purchasesLoading ? "…" : kpis.missingGrn}
          testid="kpi-po-grn"
          delta={
            !purchasesLoading && kpis.missingGrn > 0
              ? { dir: "down", text: "awaiting receipt", good: false }
              : undefined
          }
        />
        <KpiCard
          label="Variances awaiting"
          value={purchasesLoading ? "…" : kpis.variancesAwaiting}
          testid="kpi-po-variances"
          delta={
            !purchasesLoading && kpis.variancesAwaiting > 0
              ? { dir: "down", text: "needs approval", good: false }
              : undefined
          }
        />
        <KpiCard
          label="3-Way match pass"
          value={purchasesLoading ? "…" : `${kpis.matchPct}%`}
          testid="kpi-po-matchpct"
          delta={
            !purchasesLoading && threeWayRows.length > 0
              ? { dir: "up", text: "of 3-way POs clean", good: true }
              : undefined
          }
        />
        <KpiCard
          label="Needs action"
          value={purchasesLoading ? "…" : kpis.needsAction}
          testid="kpi-po-needs-action"
          onClick={kpis.needsAction > 0 ? () => setRegisterTab("action") : undefined}
          delta={
            !purchasesLoading && kpis.needsAction > 0
              ? { dir: "down", text: "not in register", good: false }
              : undefined
          }
        />
      </div>

      <PurchaseRegisterPanel
        registerRows={threeWayRows}
        twoWayRows={twoWayRows}
        purchaseRows={purchaseRows}
        actionRequired={actionRequired}
        actionCount={kpis.needsAction}
        loading={purchasesLoading}
        isError={isError}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        activeTab={registerTab}
        onTabChange={setRegisterTab}
        selectedKey={selectedKey}
        onSelectKey={setSelectedKey}
        onOpenInvoice={setDrawerInvoiceId}
        busyPurchaseId={mutations.busyId}
        onApproveVariance={(purchaseId) => void handleApproveVariance(purchaseId)}
      />

      <PurchaseDetailSheet
        open={!!selected}
        onClose={() => setSelectedKey(null)}
        title={
          <span className="flex items-center gap-2">
            {selected?.po.id}
            {selected && selected.po.invoiceNo !== "—" && (
              <span className="text-muted-foreground font-normal font-mono text-sm">
                {selected.po.invoiceNo}
              </span>
            )}
            {selected && <MatchStatusBadge status={selected.m.status} />}
          </span>
        }
        subtitle={
          selected
            ? `${selected.po.vendor} · ${selected.po.item} · requested by ${selected.po.requestor}`
            : undefined
        }
      >
        {selected && (
          <PurchaseDetailContent
            po={selected.po}
            match={selected.m}
            invoiceId={selected.invoiceId}
            twoWay={isPurchaseTwoWayMode(selected.matchMode)}
            busy={mutations.busyId === selected.purchaseId}
            canApproveVariance={selected.po.routedForApproval ?? false}
            onApprove={() => handleApproveVariance(selected.purchaseId)}
            onRecordGrn={(body) => handleRecordGrn(selected.purchaseId, body)}
            onOpenInvoice={
              selected.invoiceId != null
                ? () => setDrawerInvoiceId(selected.invoiceId)
                : undefined
            }
            onOpenPoDocument={
              selected.po.poDocumentId != null
                ? () => setDrawerInvoiceId(selected.po.poDocumentId!)
                : undefined
            }
            onOpenGrnDocument={
              selected.po.grnDocumentId != null
                ? () => setDrawerInvoiceId(selected.po.grnDocumentId!)
                : undefined
            }
          />
        )}
      </PurchaseDetailSheet>

      <LazyInvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => void refetchAll()}
        initialTab="po"
      />
    </div>
  );
}
