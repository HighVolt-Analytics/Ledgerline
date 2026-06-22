import { useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { ThreeWayAuditBadge } from "@/components/purchases/ThreeWayAuditBadge";
import { PurchaseCaptureStrip } from "@/components/purchases/PurchaseCaptureStrip";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import {
  PurchaseDetailContent,
  PurchaseDetailSheet,
  VarianceFormulaHint,
} from "@/components/purchases/PurchaseDetailPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePurchaseMutations } from "@/hooks/usePurchaseMutations";
import { usePurchases } from "@/hooks/usePurchases";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { apiPurchaseToRow, purchaseKpisFromRegister } from "@/lib/routePageAdapters";
import { fmtAud } from "@/lib/v4MockData";

const ROUTE_TARGET = "Purchase Management";
const POLL_MS = 15_000;

function purchaseRowKey(purchaseId: number, invoiceId: number | null) {
  return `${purchaseId}-${invoiceId ?? "none"}`;
}

export function PurchaseManagementPage() {
  const { data: routed = [], refetch: refetchRouted } = useRoutedInvoices(ROUTE_TARGET);
  const { data: purchaseRows = [], isLoading: purchasesLoading, isError, refetch: refetchPurchases } =
    usePurchases();
  const { data: ruleBook } = useRuleBookConfig();
  const mutations = usePurchaseMutations();

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const rows = useMemo(() => purchaseRows.map(apiPurchaseToRow), [purchaseRows]);
  const filteredRows = useMemo(
    () =>
      rows.filter(({ purchaseId, invoiceId, po, m, threeWayAuditStatus }) =>
        matchesListSearch(
          searchQuery,
          purchaseId,
          invoiceId,
          po.id,
          po.vendor,
          po.invoiceNo,
          po.item,
          po.requestor,
          m.status,
          threeWayAuditStatus
        )
      ),
    [rows, searchQuery]
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
    await Promise.all([refetchRouted(), refetchPurchases()]);
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
        subtitle="PO → GRN → Invoice three-way matching. Variances are routed for tiered approval before payment."
      />

      <PurchaseCaptureStrip activeRuleCount={activeRuleCount} />

      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 mb-5">
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
            !purchasesLoading && purchaseRows.length > 0
              ? { dir: "up", text: "of POs clean", good: true }
              : undefined
          }
        />
        <KpiCard
          label="Missing PO link"
          value={purchasesLoading ? "…" : kpis.withoutPoRef}
          testid="kpi-po-missing-ref"
          delta={
            !purchasesLoading && kpis.withoutPoRef > 0
              ? { dir: "down", text: "routed, no PO ref", good: false }
              : undefined
          }
        />
      </div>

      <RoutedInvoicesPanel
        routeTarget={ROUTE_TARGET}
        title="Documents routed to Purchase Management"
        hint="Commercial invoices and PO dossier members appear here after classification. Link a PO reference to enter the three-way match register below. Exception rows may need vendor registration in Master Data."
        testId="purchase-routed-invoices"
        showPo
      />

      <Card className="overflow-hidden mt-5">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-border">
          <div>
            <span className="text-sm font-medium">Three-way match register</span>
            <p className="text-xs text-muted-foreground mt-0.5">
              Click a row to open the three-way match detail drawer.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {rows.length > 0 ? (
              <ListSearchInput
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search this list…"
                testId="input-purchase-search"
              />
            ) : null}
            <VarianceFormulaHint />
          </div>
        </div>

        {purchasesLoading ? (
          <div className="px-4 py-8 text-sm text-muted-foreground">Loading purchase orders…</div>
        ) : isError ? (
          <div className="px-4 py-8 text-sm text-destructive">Could not load purchase orders.</div>
        ) : rows.length === 0 ? (
          <div className="px-4 py-6">
            <EmptyState
              title="No purchase orders yet"
              hint="PO-linked commercial invoices appear here after processing. Routed documents without a PO reference stay in the list above until you attach a PO number."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border text-left">
                  <th className="px-4 py-2.5 font-medium">PO</th>
                  <th className="px-3 py-2.5 font-medium">Invoice</th>
                  <th className="px-3 py-2.5 font-medium">Vendor</th>
                  <th className="px-3 py-2.5 font-medium">Date</th>
                  <th className="px-3 py-2.5 font-medium text-right">PO Qty · Value</th>
                  <th className="px-3 py-2.5 font-medium text-right">GRN Qty · Date</th>
                  <th className="px-3 py-2.5 font-medium text-right">Invoice Qty · Value</th>
                  <th className="px-3 py-2.5 font-medium text-right">Qty Var.</th>
                  <th className="px-3 py-2.5 font-medium text-right">Price Var.</th>
                  <th className="px-3 py-2.5 font-medium">Match</th>
                  <th className="px-3 py-2.5 font-medium">3-Way audit</th>
                  <th className="px-4 py-2.5 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 && (
                  <tr>
                    <td colSpan={12} className="px-4 py-8 text-center text-muted-foreground">
                      No purchase orders match your search.
                    </td>
                  </tr>
                )}
                {filteredRows.map(({ purchaseId, invoiceId, po, m, threeWayAuditStatus }) => {
                  const rowKey = purchaseRowKey(purchaseId, invoiceId);
                  const showApprove = po.routedForApproval;
                  return (
                    <tr
                      key={rowKey}
                      className="row-band border-b border-border/60 hover-elevate cursor-pointer"
                      data-testid={`po-row-${po.id}-${invoiceId ?? "none"}`}
                      onClick={() => setSelectedKey(rowKey)}
                    >
                      <td className="px-4 py-2.5 font-medium whitespace-nowrap">{po.id}</td>
                      <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap font-mono text-xs">
                        {po.invoiceNo !== "—" ? po.invoiceNo : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                        {po.vendor}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground tnum whitespace-nowrap">
                        {po.date}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                        {po.poQty} · {fmtAud(m.poValue)}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                        {po.grnQty === null ? (
                          <span className="text-destructive">— no GRN</span>
                        ) : (
                          <>
                            {po.grnQty} · {po.grnDate}
                          </>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                        {po.invoiceQty} · {fmtAud(m.invoiceValue)}
                      </td>
                      <td
                        className={cn(
                          "px-3 py-2.5 text-right tnum whitespace-nowrap",
                          m.qtyVarianceValue !== 0 &&
                            "text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)] font-medium"
                        )}
                      >
                        {m.qtyVarianceValue === 0 ? "—" : fmtAud(m.qtyVarianceValue)}
                      </td>
                      <td
                        className={cn(
                          "px-3 py-2.5 text-right tnum whitespace-nowrap",
                          m.priceVarianceValue !== 0 &&
                            "text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)] font-medium"
                        )}
                      >
                        {m.priceVarianceValue === 0 ? "—" : fmtAud(m.priceVarianceValue)}
                      </td>
                      <td className="px-3 py-2.5">
                        <MatchStatusBadge status={m.status} />
                      </td>
                      <td className="px-3 py-2.5">
                        <ThreeWayAuditBadge status={threeWayAuditStatus} />
                      </td>
                      <td
                        className="px-4 py-2.5 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {showApprove ? (
                          <Button
                            size="sm"
                            className="h-7 text-xs"
                            disabled={mutations.busyId === purchaseId}
                            onClick={() => void handleApproveVariance(purchaseId)}
                            data-testid={`button-approve-variance-${po.id}`}
                          >
                            <Check className="h-3.5 w-3.5 mr-1" />
                            {mutations.busyId === purchaseId ? "…" : "Approve"}
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs text-muted-foreground"
                            onClick={() => setSelectedKey(rowKey)}
                            data-testid={`button-view-po-${po.id}-${invoiceId ?? "none"}`}
                          >
                            View
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {!purchasesLoading && rows.length > 0 && (
          <p className="px-4 py-3 text-xs text-muted-foreground border-t border-border">
            A clean three-way match requires PO quantity = GRN quantity = Invoice quantity, and PO
            unit price = Invoice unit price. Any deviation is routed for tiered approval before the
            invoice can progress to payment.
          </p>
        )}
      </Card>

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
      />
    </div>
  );
}
