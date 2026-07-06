import { useEffect, useMemo, useState } from "react";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { SalesCaptureStrip } from "@/components/sales/SalesCaptureStrip";
import {
  SalesDetailContent,
  SalesDetailSheet,
} from "@/components/sales/SalesDetailPanel";
import {
  SalesRegisterPanel,
  type SalesRegisterTab,
} from "@/components/sales/SalesRegisterPanel";
import { useSalesMutations } from "@/hooks/useSalesMutations";
import { useSales } from "@/hooks/useSales";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { useSalesTwoWay } from "@/hooks/useSalesTwoWay";
import { salesActionRequiredInvoices } from "@/lib/salesRegisterQueue";
import {
  apiSalesToRow,
  apiTwoWaySalesOrphanToRow,
  isSalesTwoWayMode,
  salesKpisFromRegister,
  type SalesRegisterTableRow,
  type SalesTwoWayOrphanRow,
} from "@/lib/routePageAdapters";

const ROUTE_TARGET = "Sales Management";
const POLL_MS = 15_000;

function salesRowKey(salesId: number, invoiceId: number | null) {
  return `${salesId}-${invoiceId ?? "none"}`;
}

export function SalesManagementPage() {
  const {
    data: routed = [],
    refetch: refetchRouted,
    blocked: routedBlocked,
  } = useRoutedInvoices(ROUTE_TARGET);
  const {
    data: salesRows = [],
    isLoading: salesLoading,
    isError,
    refetch: refetchSales,
    blocked: salesBlocked,
  } = useSales();
  const tenantDataBlocked = routedBlocked || salesBlocked;
  const {
    data: twoWayData,
    isLoading: twoWayLoading,
    refetch: refetchSalesTwoWay,
  } = useSalesTwoWay(!tenantDataBlocked);
  const { data: ruleBook } = useRuleBookConfig();
  const mutations = useSalesMutations();

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [registerTab, setRegisterTab] = useState<SalesRegisterTab>("register");

  const rows = useMemo(
    () => (tenantDataBlocked ? [] : salesRows).map(apiSalesToRow),
    [salesRows, tenantDataBlocked]
  );
  const threeWayRows = useMemo(
    () => rows.filter((row) => !isSalesTwoWayMode(row.matchMode)),
    [rows]
  );
  const twoWayRows = useMemo((): SalesRegisterTableRow[] => {
    if (tenantDataBlocked) return [];
    const registerTwoWay = rows
      .filter((row) => isSalesTwoWayMode(row.matchMode))
      .map((row) => ({ kind: "register" as const, ...row }));
    const orphans = (twoWayData?.orphan_rows ?? []).map(apiTwoWaySalesOrphanToRow);
    return [...registerTwoWay, ...orphans];
  }, [rows, twoWayData, tenantDataBlocked]);
  const actionRequired = useMemo(
    () => (tenantDataBlocked ? [] : salesActionRequiredInvoices(routed, salesRows)),
    [routed, salesRows, tenantDataBlocked]
  );
  const kpis = useMemo(
    () =>
      salesKpisFromRegister(
        tenantDataBlocked ? [] : salesRows,
        tenantDataBlocked ? [] : routed
      ),
    [salesRows, routed, tenantDataBlocked]
  );
  const selected =
    rows.find((r) => salesRowKey(r.salesId, r.invoiceId) === selectedKey) ?? null;
  const selectedTwoWayOrphan =
    twoWayRows.find(
      (r): r is SalesTwoWayOrphanRow =>
        r.kind === "orphan" && `orphan-${r.invoiceId}` === selectedKey
    ) ?? null;
  const activeRuleCount = useMemo(
    () => (ruleBook?.salesRules ?? []).filter((r) => r.enabled).length,
    [ruleBook?.salesRules]
  );

  const refetchAll = async () => {
    await Promise.all([refetchRouted(), refetchSales(), refetchSalesTwoWay()]);
  };

  useVisibilityPolling(() => {
    void refetchAll();
  }, POLL_MS);

  useEffect(() => {
    if (selectedKey && !rows.some((r) => salesRowKey(r.salesId, r.invoiceId) === selectedKey)) {
      setSelectedKey(null);
    }
  }, [selectedKey, rows]);

  useEffect(() => {
    if (!mutations.toast) return;
    const t = setTimeout(() => mutations.setToast(null), 3000);
    return () => clearTimeout(t);
  }, [mutations.toast, mutations.setToast]);

  const handleApproveVariance = async (salesId: number) => {
    await mutations.approveVariance(salesId);
  };

  const handleRecordDn = async (
    salesId: number,
    body: { dn_qty: number; shipper?: string; condition_note?: string }
  ) => {
    await mutations.recordDeliveryNote(salesId, body);
  };

  return (
    <div>
      {mutations.toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {mutations.toast}
        </div>
      )}

      <PageHeader
        title="Sales Management"
        subtitle="SO → DN → Invoice three-way matching. Variances route for tiered approval before collections."
      />

      <SalesCaptureStrip activeRuleCount={activeRuleCount} />

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 mb-5">
        <KpiCard
          label="Open SOs"
          value={salesLoading ? "…" : kpis.openSos}
          testid="kpi-sales-open"
        />
        <KpiCard
          label="Pending DN"
          value={salesLoading ? "…" : kpis.missingDn}
          testid="kpi-sales-dn"
          delta={
            !salesLoading && kpis.missingDn > 0
              ? { dir: "down", text: "awaiting delivery", good: false }
              : undefined
          }
        />
        <KpiCard
          label="3-Way match pass"
          value={salesLoading ? "…" : `${kpis.matchPct}%`}
          testid="kpi-sales-matchpct"
          delta={
            !salesLoading && threeWayRows.length > 0
              ? { dir: "up", text: "of 3-way SOs clean", good: true }
              : undefined
          }
        />
        <KpiCard
          label="2-Way match pass"
          value={salesLoading || twoWayLoading ? "…" : `${kpis.twoWayMatchPct}%`}
          testid="kpi-sales-two-way-matchpct"
          onClick={kpis.twoWayCount > 0 ? () => setRegisterTab("two_way") : undefined}
          delta={
            !salesLoading && kpis.twoWayCount > 0
              ? { dir: "up", text: `${kpis.twoWayCount} DN↔Invoice`, good: true }
              : undefined
          }
        />
        <KpiCard
          label="Needs action"
          value={salesLoading ? "…" : kpis.needsAction}
          testid="kpi-sales-needs-action"
          onClick={kpis.needsAction > 0 ? () => setRegisterTab("action") : undefined}
          delta={
            !salesLoading && kpis.needsAction > 0
              ? { dir: "down", text: "not in register", good: false }
              : undefined
          }
        />
      </div>

      <SalesRegisterPanel
        registerRows={threeWayRows}
        twoWayRows={twoWayRows}
        salesRows={salesRows}
        actionRequired={actionRequired}
        loading={salesLoading || twoWayLoading || tenantDataBlocked}
        isError={isError}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        activeTab={registerTab}
        onTabChange={setRegisterTab}
        selectedKey={selectedKey}
        onSelectKey={setSelectedKey}
        onOpenInvoice={setDrawerInvoiceId}
        busySalesId={mutations.busyId}
        onApproveVariance={(salesId) => void handleApproveVariance(salesId)}
      />

      <SalesDetailSheet
        open={!!selected || !!selectedTwoWayOrphan}
        onClose={() => setSelectedKey(null)}
        title={
          selectedTwoWayOrphan ? (
            <span className="flex items-center gap-2">
              {selectedTwoWayOrphan.invoiceNo}
              <MatchStatusBadge status={selectedTwoWayOrphan.m.status} />
            </span>
          ) : (
            <span className="flex items-center gap-2">
              {selected?.so.id}
              {selected && selected.so.invoiceNo !== "—" && (
                <span className="text-muted-foreground font-normal font-mono text-sm">
                  {selected.so.invoiceNo}
                </span>
              )}
              {selected && <MatchStatusBadge status={selected.m.status} />}
            </span>
          )
        }
        subtitle={
          selectedTwoWayOrphan
            ? `${selectedTwoWayOrphan.customer} · DN ↔ Invoice two-way match`
            : selected
              ? `${selected.so.customer} · ${selected.so.item} · requested by ${selected.so.requestor}`
              : undefined
        }
      >
        {selectedTwoWayOrphan ? (
          <SalesDetailContent
            match={selectedTwoWayOrphan.m}
            invoiceId={selectedTwoWayOrphan.invoiceId}
            twoWay
            dnQty={selectedTwoWayOrphan.dnQty}
            invoiceQty={selectedTwoWayOrphan.invoiceQty}
            onOpenInvoice={() => setDrawerInvoiceId(selectedTwoWayOrphan.invoiceId)}
            onOpenDnDocument={
              selectedTwoWayOrphan.dnInvoiceId != null
                ? () => setDrawerInvoiceId(selectedTwoWayOrphan.dnInvoiceId!)
                : undefined
            }
          />
        ) : (
          selected && (
            <SalesDetailContent
              so={selected.so}
              match={selected.m}
              invoiceId={selected.invoiceId}
              twoWay={isSalesTwoWayMode(selected.matchMode)}
              busy={mutations.busyId === selected.salesId}
              canApproveVariance={selected.so.routedForApproval ?? false}
              onApprove={() => handleApproveVariance(selected.salesId)}
              onRecordDn={(body) => handleRecordDn(selected.salesId, body)}
              onOpenInvoice={
                selected.invoiceId != null
                  ? () => setDrawerInvoiceId(selected.invoiceId)
                  : undefined
              }
              onOpenSoDocument={
                selected.so.soDocumentId != null
                  ? () => setDrawerInvoiceId(selected.so.soDocumentId!)
                  : undefined
              }
              onOpenDnDocument={
                selected.so.dnDocumentId != null
                  ? () => setDrawerInvoiceId(selected.so.dnDocumentId!)
                  : undefined
              }
            />
          )
        )}
      </SalesDetailSheet>

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
