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
import { salesActionRequiredInvoices } from "@/lib/salesRegisterQueue";
import { apiSalesToRow, salesKpisFromRegister } from "@/lib/routePageAdapters";

const ROUTE_TARGET = "Sales Management";
const POLL_MS = 15_000;

function salesRowKey(salesId: number, invoiceId: number | null) {
  return `${salesId}-${invoiceId ?? "none"}`;
}

export function SalesManagementPage() {
  const { data: routed = [], refetch: refetchRouted } = useRoutedInvoices(ROUTE_TARGET);
  const {
    data: salesRows = [],
    isLoading: salesLoading,
    isError,
    refetch: refetchSales,
  } = useSales();
  const { data: ruleBook } = useRuleBookConfig();
  const mutations = useSalesMutations();

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [registerTab, setRegisterTab] = useState<SalesRegisterTab>("register");

  const rows = useMemo(() => salesRows.map(apiSalesToRow), [salesRows]);
  const actionRequired = useMemo(
    () => salesActionRequiredInvoices(routed, salesRows),
    [routed, salesRows]
  );
  const kpis = useMemo(
    () => salesKpisFromRegister(salesRows, routed),
    [salesRows, routed]
  );
  const selected =
    rows.find((r) => salesRowKey(r.salesId, r.invoiceId) === selectedKey) ?? null;
  const activeRuleCount = useMemo(
    () => (ruleBook?.salesRules ?? []).filter((r) => r.enabled).length,
    [ruleBook?.salesRules]
  );

  const refetchAll = async () => {
    await Promise.all([refetchRouted(), refetchSales()]);
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

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 mb-5">
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
            !salesLoading && salesRows.length > 0
              ? { dir: "up", text: "of SOs clean", good: true }
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
        registerRows={rows}
        salesRows={salesRows}
        actionRequired={actionRequired}
        loading={salesLoading}
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
        open={!!selected}
        onClose={() => setSelectedKey(null)}
        title={
          <span className="flex items-center gap-2">
            {selected?.so.id}
            {selected && selected.so.invoiceNo !== "—" && (
              <span className="text-muted-foreground font-normal font-mono text-sm">
                {selected.so.invoiceNo}
              </span>
            )}
            {selected && <MatchStatusBadge status={selected.m.status} />}
          </span>
        }
        subtitle={
          selected
            ? `${selected.so.customer} · ${selected.so.item} · requested by ${selected.so.requestor}`
            : undefined
        }
      >
        {selected && (
          <SalesDetailContent
            so={selected.so}
            match={selected.m}
            invoiceId={selected.invoiceId}
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
