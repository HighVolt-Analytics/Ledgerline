import { useEffect, useMemo, useState } from "react";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
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
import { usePurchases } from "@/hooks/usePurchases";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { usePurchasesTwoWay } from "@/hooks/usePurchasesTwoWay";
import { purchaseActionRequiredInvoices } from "@/lib/purchaseRegisterQueue";
import {
  apiPurchaseToRow,
  isPurchaseTwoWayMode,
  purchaseKpisFromRegister,
} from "@/lib/routePageAdapters";

const ROUTE_TARGET = "Purchase Management";
const POLL_MS = 15_000;

function purchaseRowKey(purchaseId: number, invoiceId: number | null) {
  return `${purchaseId}-${invoiceId ?? "none"}`;
}

export function PurchaseManagementPage() {
  const { data: routed = [], refetch: refetchRouted } = useRoutedInvoices(ROUTE_TARGET);
  const {
    data: purchaseRows = [],
    isLoading: purchasesLoading,
    isError,
    refetch: refetchPurchases,
  } = usePurchases();
  const { data: twoWayPurchaseRows = [], refetch: refetchPurchasesTwoWay } = usePurchasesTwoWay();
  const { data: ruleBook } = useRuleBookConfig();
  const mutations = usePurchaseMutations();

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [registerTab, setRegisterTab] = useState<PurchaseRegisterTab>("register");

  const rows = useMemo(() => purchaseRows.map(apiPurchaseToRow), [purchaseRows]);
  const threeWayRows = useMemo(
    () => rows.filter((row) => !isPurchaseTwoWayMode(row.matchMode)),
    [rows]
  );
  const twoWayRows = useMemo(
    () => twoWayPurchaseRows.map(apiPurchaseToRow),
    [twoWayPurchaseRows]
  );
  const actionRequired = useMemo(
    () => purchaseActionRequiredInvoices(routed, purchaseRows),
    [routed, purchaseRows]
  );
  const kpis = useMemo(
    () => purchaseKpisFromRegister(purchaseRows, routed),
    [purchaseRows, routed]
  );
  const selected =
    rows.find((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey) ?? null;
  const activeRuleCount = useMemo(
    () => (ruleBook?.purchaseRules ?? []).filter((r) => r.enabled).length,
    [ruleBook?.purchaseRules]
  );

  const refetchAll = async () => {
    await Promise.all([refetchRouted(), refetchPurchases(), refetchPurchasesTwoWay()]);
  };

  useVisibilityPolling(() => {
    void refetchAll();
  }, POLL_MS);

  useEffect(() => {
    if (selectedKey && !rows.some((r) => purchaseRowKey(r.purchaseId, r.invoiceId) === selectedKey)) {
      setSelectedKey(null);
    }
  }, [selectedKey, rows]);

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

      <PageHeader
        title="Purchase Management"
        subtitle="PO → GRN → Invoice matching (3-way or 2-way per playbook). Variances are routed for tiered approval before payment."
      />

      <PurchaseCaptureStrip activeRuleCount={activeRuleCount} />

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 mb-5">
        <KpiCard
          label="Open POs"
          value={purchasesLoading ? "…" : kpis.openPos}
          testid="kpi-po-open"
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
          label="2-Way match pass"
          value={purchasesLoading ? "…" : `${kpis.twoWayMatchPct}%`}
          testid="kpi-po-two-way-matchpct"
          onClick={kpis.twoWayCount > 0 ? () => setRegisterTab("two_way") : undefined}
          delta={
            !purchasesLoading && kpis.twoWayCount > 0
              ? { dir: "up", text: `${kpis.twoWayCount} PO↔Invoice`, good: true }
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

      <InvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => void refetchAll()}
        initialTab="po"
      />
    </div>
  );
}
