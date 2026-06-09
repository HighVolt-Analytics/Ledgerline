import { useMemo, useState } from "react";
import { Check } from "lucide-react";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import {
  PurchaseDetailContent,
  PurchaseDetailSheet,
  VarianceFormulaHint,
} from "@/components/purchases/PurchaseDetailPanel";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { purchaseKpisFromInvoices } from "@/lib/routePageAdapters";
import {
  computeThreeWayMatch,
  fmtAud,
  INITIAL_PURCHASES,
  SANDBOX_APPROVER_ID,
  SANDBOX_CURRENT_USER,
} from "@/lib/v4MockData";

export function PurchaseManagementPage() {
  const { data: routed = [], isLoading: routedLoading } = useRoutedInvoices(
    "Purchase Management"
  );
  const [purchases, setPurchases] = useState(INITIAL_PURCHASES);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showSandbox, setShowSandbox] = useState(false);

  const sandboxRows = useMemo(
    () => purchases.map((po) => ({ po, m: computeThreeWayMatch(po) })),
    [purchases]
  );

  const kpis = useMemo(() => purchaseKpisFromInvoices(routed), [routed]);

  const selected = sandboxRows.find((r) => r.po.id === selectedId) ?? null;

  const approveVariance = (poId: string) => {
    setPurchases((list) =>
      list.map((po) => {
        if (po.id !== poId || !po.approvers) return po;
        const next = po.approvers.map((a) =>
          a.id === SANDBOX_APPROVER_ID && a.state === "pending"
            ? { ...a, state: "approved" as const, ts: "2026-05-30 09:00" }
            : a
        );
        const stillPending = next.some((a) => a.state === "pending");
        return { ...po, approvers: next, routedForApproval: stillPending };
      })
    );
  };

  return (
    <div>
      <PageHeader
        title="Purchase Management"
        subtitle="PO → GRN → Invoice three-way matching. Routed purchase documents come from the Rule Book pipeline."
      />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard
          label="Open documents"
          value={routedLoading ? "…" : kpis.openPos}
          testid="kpi-po-open"
        />
        <KpiCard
          label="Without PO ref"
          value={routedLoading ? "…" : kpis.pendingGrn}
          testid="kpi-po-grn"
          delta={
            !routedLoading && kpis.pendingGrn > 0
              ? { dir: "flat", text: "missing PO link" }
              : undefined
          }
        />
        <KpiCard
          label="Processed"
          value={routedLoading ? "…" : `${kpis.matchPct}%`}
          testid="kpi-po-matchpct"
          delta={
            !routedLoading && routed.length > 0
              ? { dir: "up", text: "of routed docs", good: true }
              : undefined
          }
        />
        <KpiCard
          label="Needs review"
          value={routedLoading ? "…" : kpis.variancesAwaiting}
          testid="kpi-po-variances"
          delta={
            !routedLoading && kpis.variancesAwaiting > 0
              ? { dir: "down", text: "exceptions / review", good: false }
              : undefined
          }
        />
      </div>

      <RoutedInvoicesPanel
        routeTarget="Purchase Management"
        title="Documents routed from Rule Book"
        hint="Invoices whose email capture or purchase rules assigned Purchase Management. Run remap after rule changes."
        testId="purchase-routed-invoices"
        showPo
      />

      <Card className="overflow-hidden mt-5">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-border">
          <div>
            <span className="text-sm font-medium">Three-way match sandbox</span>
            <p className="text-xs text-muted-foreground mt-0.5">
              Demo PO/GRN register until purchase-order APIs are connected. Live documents are in
              the table above.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <VarianceFormulaHint />
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => setShowSandbox((v) => !v)}
              data-testid="toggle-po-sandbox"
            >
              {showSandbox ? "Hide demo" : "Show demo"}
            </Button>
          </div>
        </div>
        {showSandbox ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b border-border text-left">
                  <th className="px-4 py-2.5 font-medium">PO</th>
                  <th className="px-3 py-2.5 font-medium">Vendor</th>
                  <th className="px-3 py-2.5 font-medium">Date</th>
                  <th className="px-3 py-2.5 font-medium text-right">PO Qty · Value</th>
                  <th className="px-3 py-2.5 font-medium text-right">GRN Qty · Date</th>
                  <th className="px-3 py-2.5 font-medium text-right">Invoice Qty · Value</th>
                  <th className="px-3 py-2.5 font-medium text-right">Qty Var.</th>
                  <th className="px-3 py-2.5 font-medium text-right">Price Var.</th>
                  <th className="px-3 py-2.5 font-medium">Match Status</th>
                  <th className="px-4 py-2.5 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {sandboxRows.map(({ po, m }) => {
                  const pending = po.approvers?.find((a) => a.state === "pending");
                  const canRowApprove = pending?.id === SANDBOX_CURRENT_USER.id;
                  return (
                    <tr
                      key={po.id}
                      className="row-band border-b border-border/60 hover-elevate cursor-pointer"
                      data-testid={`po-row-${po.id}`}
                      onClick={() => setSelectedId(po.id)}
                    >
                      <td className="px-4 py-2.5 font-medium whitespace-nowrap">{po.id}</td>
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
                      <td
                        className="px-4 py-2.5 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {canRowApprove ? (
                          <Button
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => approveVariance(po.id)}
                            data-testid={`button-approve-variance-${po.id}`}
                          >
                            <Check className="h-3.5 w-3.5 mr-1" /> Approve
                          </Button>
                        ) : pending ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            disabled
                            title={`Next approver in chain: ${pending.name} (${pending.role}).`}
                            data-testid={`button-approve-variance-${po.id}`}
                          >
                            Awaiting {pending.name.split(" ")[0]}
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs text-muted-foreground"
                            onClick={() => setSelectedId(po.id)}
                            data-testid={`button-view-po-${po.id}`}
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
        ) : (
          <div className="px-4 py-6 text-sm text-muted-foreground">
            Expand the sandbox to explore three-way match variance approval flows with sample PO
            data.
          </div>
        )}
      </Card>

      <PurchaseDetailSheet
        open={!!selected}
        onClose={() => setSelectedId(null)}
        title={
          <span className="flex items-center gap-2">
            {selected?.po.id} {selected && <MatchStatusBadge status={selected.m.status} />}
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
            onApprove={() => {
              approveVariance(selected.po.id);
              setSelectedId(null);
            }}
          />
        )}
      </PurchaseDetailSheet>
    </div>
  );
}
