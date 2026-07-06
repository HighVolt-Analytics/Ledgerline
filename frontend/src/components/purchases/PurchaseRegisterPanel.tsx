import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, ClipboardList } from "lucide-react";
import type { Invoice, PurchaseOrderApi } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";
import { EvaluationStatusBadge } from "@/components/inbox/EvaluationStatusBadge";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageTabs } from "@/components/PageTabs";
import { invoiceStageBadgeProps, StageBadge } from "@/components/StageBadge";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { ThreeWayAuditBadge } from "@/components/purchases/ThreeWayAuditBadge";
import { ListPaginationFooter } from "@/components/purchases/ListPaginationFooter";
import { VarianceFormulaHint } from "@/components/purchases/PurchaseDetailPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { cn } from "@/lib/cn";
import { documentDisplayRef, money } from "@/lib/format";
import { invoiceDocumentTypeDisplayLabel } from "@/lib/documentTypeResolve";
import { invoiceValidationConfidence } from "@/lib/invoice";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { buildPurchaseRegisterCoverage, purchaseActionIssue } from "@/lib/purchaseRegisterQueue";
import { fmtAud } from "@/lib/v4MockData";
import type { apiPurchaseToRow } from "@/lib/routePageAdapters";

const PAGE_SIZE = 10;

type RegisterRow = ReturnType<typeof apiPurchaseToRow>;

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function purchaseRowKey(purchaseId: number, invoiceId: number | null) {
  return `${purchaseId}-${invoiceId ?? "none"}`;
}

export type PurchaseRegisterTab = "register" | "two_way" | "action";

export function PurchaseTwoWayFormulaHint() {
  return (
    <p className="text-xs text-muted-foreground">
      Two-way match: <span className="font-mono">PO qty/price ↔ Invoice qty/price</span> (service PO profiles).
    </p>
  );
}

export function PurchaseRegisterPanel({
  registerRows,
  twoWayRows,
  purchaseRows,
  actionRequired,
  loading,
  isError,
  searchQuery,
  onSearchChange,
  activeTab,
  onTabChange,
  selectedKey,
  onSelectKey,
  onOpenInvoice,
  busyPurchaseId,
  onApproveVariance,
}: {
  registerRows: RegisterRow[];
  twoWayRows: RegisterRow[];
  purchaseRows: PurchaseOrderApi[];
  actionRequired: Invoice[];
  loading: boolean;
  isError: boolean;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  activeTab: PurchaseRegisterTab;
  onTabChange: (tab: PurchaseRegisterTab) => void;
  selectedKey: string | null;
  onSelectKey: (key: string | null) => void;
  onOpenInvoice: (invoiceId: number) => void;
  busyPurchaseId: number | null;
  onApproveVariance: (purchaseId: number) => void;
}) {
  const { data: ruleBook } = useRuleBookConfig();
  const [registerPage, setRegisterPage] = useState(1);
  const [twoWayPage, setTwoWayPage] = useState(1);
  const [actionPage, setActionPage] = useState(1);

  const coverage = useMemo(
    () => buildPurchaseRegisterCoverage(purchaseRows),
    [purchaseRows]
  );

  const filteredRegister = useMemo(
    () =>
      registerRows.filter(({ purchaseId, invoiceId, po, m, threeWayAuditStatus }) => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return true;
        return [
          purchaseId,
          invoiceId,
          po.id,
          po.vendor,
          po.invoiceNo,
          po.item,
          po.requestor,
          m.status,
          threeWayAuditStatus,
        ].some((v) => String(v ?? "").toLowerCase().includes(q));
      }),
    [registerRows, searchQuery]
  );

  const filteredAction = useMemo(
    () => actionRequired.filter((inv) => invoiceMatchesListSearch(inv, searchQuery)),
    [actionRequired, searchQuery]
  );

  const filteredTwoWay = useMemo(
    () =>
      twoWayRows.filter(({ purchaseId, invoiceId, po, m, threeWayAuditStatus }) => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return true;
        return [
          purchaseId,
          invoiceId,
          po.id,
          po.vendor,
          po.invoiceNo,
          m.status,
          threeWayAuditStatus,
        ].some((v) => String(v ?? "").toLowerCase().includes(q));
      }),
    [twoWayRows, searchQuery]
  );

  const registerPages = Math.max(1, Math.ceil(filteredRegister.length / PAGE_SIZE));
  const twoWayPages = Math.max(1, Math.ceil(filteredTwoWay.length / PAGE_SIZE));
  const actionPages = Math.max(1, Math.ceil(filteredAction.length / PAGE_SIZE));

  const pagedRegister = filteredRegister.slice(
    (registerPage - 1) * PAGE_SIZE,
    registerPage * PAGE_SIZE
  );
  const pagedTwoWay = filteredTwoWay.slice(
    (twoWayPage - 1) * PAGE_SIZE,
    twoWayPage * PAGE_SIZE
  );
  const pagedAction = filteredAction.slice(
    (actionPage - 1) * PAGE_SIZE,
    actionPage * PAGE_SIZE
  );

  useEffect(() => {
    setRegisterPage(1);
    setTwoWayPage(1);
    setActionPage(1);
  }, [searchQuery, activeTab]);

  useEffect(() => {
    if (twoWayPage > twoWayPages) setTwoWayPage(twoWayPages);
  }, [twoWayPage, twoWayPages]);

  useEffect(() => {
    if (registerPage > registerPages) setRegisterPage(registerPages);
  }, [registerPage, registerPages]);

  useEffect(() => {
    if (actionPage > actionPages) setActionPage(actionPages);
  }, [actionPage, actionPages]);

  const showActionBanner =
    activeTab === "register" && actionRequired.length > 0 && !loading;

  return (
    <Card className="overflow-hidden" data-testid="purchase-register-panel">
      <div className="px-4 pt-3 pb-2 border-b border-border space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-primary shrink-0" />
              Purchase register
            </h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-full whitespace-nowrap truncate">
              Three-way match for PO-linked invoices. Unlinked or unsynced documents are in the second tab.
            </p>
          </div>
          {(registerRows.length > 0 || twoWayRows.length > 0 || actionRequired.length > 0) && (
            <ListSearchInput
              value={searchQuery}
              onChange={onSearchChange}
              placeholder="Search register…"
              testId="input-purchase-search"
            />
          )}
        </div>

        <PageTabs
          value={activeTab}
          onChange={(v) => onTabChange(v as PurchaseRegisterTab)}
          data-testid="purchase-register-tabs"
          tabs={[
            {
              value: "register",
              testid: "tab-purchase-register",
              label: (
                <>
                  Three-way match
                  <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                    {registerRows.length}
                  </Badge>
                </>
              ),
            },
            {
              value: "two_way",
              testid: "tab-purchase-two-way",
              label: (
                <>
                  Two-way match
                  <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                    {twoWayRows.length}
                  </Badge>
                </>
              ),
            },
            {
              value: "action",
              testid: "tab-purchase-action",
              label: (
                <>
                  Needs action
                  <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                    {actionRequired.length}
                  </Badge>
                </>
              ),
            },
          ]}
        />
      </div>

      {showActionBanner ? (
        <div
          className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border ds-warning-panel-strong px-3 py-2 text-xs"
          role="status"
        >
          <span className="inline-flex items-center gap-1.5 text-foreground">
            <AlertTriangle className="h-3.5 w-3.5 ds-warning-text shrink-0" />
            {actionRequired.length} document{actionRequired.length === 1 ? "" : "s"} need attention
            before three-way match.
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => onTabChange("action")}
            data-testid="button-view-purchase-action"
          >
            View queue
          </Button>
        </div>
      ) : null}

      {activeTab === "register" ? (
        <>
          <div className="flex flex-wrap items-center justify-end gap-2 px-4 py-2 border-b border-border/60">
            <VarianceFormulaHint />
          </div>

          {loading ? (
            <InlineTableSkeleton rows={6} columns={12} />
          ) : isError ? (
            <div className="px-4 py-8 text-sm text-destructive">Could not load purchase register.</div>
          ) : registerRows.length === 0 ? (
            <div className="px-4 py-6">
              <EmptyState
                title="No PO register rows yet"
                hint={
                  actionRequired.length > 0
                    ? "Link PO references on routed documents in Needs action, or ingest PO documents first."
                    : "Commercial invoices with a valid PO reference appear here after processing."
                }
                action={
                  actionRequired.length > 0 ? (
                    <Button size="sm" variant="outline" onClick={() => onTabChange("action")}>
                      Open needs action ({actionRequired.length})
                    </Button>
                  ) : undefined
                }
              />
            </div>
          ) : (
            <>
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
                    {pagedRegister.length === 0 && (
                      <tr>
                        <td colSpan={12} className="px-4 py-8 text-center text-muted-foreground">
                          No register rows match your search.
                        </td>
                      </tr>
                    )}
                    {pagedRegister.map(({ purchaseId, invoiceId, po, m, threeWayAuditStatus }) => {
                      const rowKey = purchaseRowKey(purchaseId, invoiceId);
                      const showApprove = po.routedForApproval;
                      return (
                        <tr
                          key={rowKey}
                          className={cn(
                            "row-band border-b border-border/60 hover-elevate cursor-pointer",
                            selectedKey === rowKey && "bg-muted/40"
                          )}
                          data-testid={`po-row-${po.id}-${invoiceId ?? "none"}`}
                          onClick={() => onSelectKey(rowKey)}
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
                                "ds-warning-text font-medium"
                            )}
                          >
                            {m.qtyVarianceValue === 0 ? "—" : fmtAud(m.qtyVarianceValue)}
                          </td>
                          <td
                            className={cn(
                              "px-3 py-2.5 text-right tnum whitespace-nowrap",
                              m.priceVarianceValue !== 0 &&
                                "ds-warning-text font-medium"
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
                                disabled={busyPurchaseId === purchaseId}
                                onClick={() => onApproveVariance(purchaseId)}
                                data-testid={`button-approve-variance-${po.id}`}
                              >
                                <Check className="h-3.5 w-3.5 mr-1" />
                                {busyPurchaseId === purchaseId ? "…" : "Approve"}
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-xs text-muted-foreground"
                                onClick={() => onSelectKey(rowKey)}
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
              <ListPaginationFooter
                page={registerPage}
                totalPages={registerPages}
                pageSize={PAGE_SIZE}
                onPageChange={setRegisterPage}
              />
              {!loading && registerRows.length > 0 ? (
                <p className="px-4 py-3 text-xs text-muted-foreground border-t border-border">
                  A clean three-way match requires PO quantity = GRN quantity = Invoice quantity,
                  and PO unit price = Invoice unit price. Variances route for tiered approval before
                  payment.
                </p>
              ) : null}
            </>
          )}
        </>
      ) : activeTab === "two_way" ? (
        <>
          <div className="flex flex-wrap items-center justify-end gap-2 px-4 py-2 border-b border-border/60">
            <PurchaseTwoWayFormulaHint />
          </div>

          {loading ? (
            <InlineTableSkeleton rows={5} columns={9} />
          ) : isError ? (
            <div className="px-4 py-8 text-sm text-destructive">Could not load two-way matches.</div>
          ) : twoWayRows.length === 0 ? (
            <div className="px-4 py-6">
              <EmptyState
                title="No two-way matches yet"
                hint="Service PO documents on 2-way playbook profiles (PO ↔ Invoice) appear here when linked."
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground border-b border-border text-left">
                      <th className="px-4 py-2.5 font-medium">PO</th>
                      <th className="px-3 py-2.5 font-medium">Invoice</th>
                      <th className="px-3 py-2.5 font-medium">Vendor</th>
                      <th className="px-3 py-2.5 font-medium text-right">PO Qty · Value</th>
                      <th className="px-3 py-2.5 font-medium text-right">Invoice Qty · Value</th>
                      <th className="px-3 py-2.5 font-medium text-right">Qty Var.</th>
                      <th className="px-3 py-2.5 font-medium text-right">Price Var.</th>
                      <th className="px-3 py-2.5 font-medium">Match</th>
                      <th className="px-4 py-2.5 font-medium text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedTwoWay.length === 0 && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                          No two-way rows match your search.
                        </td>
                      </tr>
                    )}
                    {pagedTwoWay.map(({ purchaseId, invoiceId, po, m }) => {
                      const rowKey = purchaseRowKey(purchaseId, invoiceId);
                      return (
                        <tr
                          key={rowKey}
                          className={cn(
                            "row-band border-b border-border/60 hover-elevate cursor-pointer",
                            selectedKey === rowKey && "bg-muted/40"
                          )}
                          onClick={() => onSelectKey(rowKey)}
                        >
                          <td className="px-4 py-2.5 font-medium">{po.id}</td>
                          <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">
                            {po.invoiceNo !== "—" ? po.invoiceNo : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-muted-foreground">{po.vendor}</td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {po.poQty} · {fmtAud(m.poValue)}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {po.invoiceQty} · {fmtAud(m.invoiceValue)}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {m.qtyVarianceValue === 0 ? "—" : fmtAud(m.qtyVarianceValue)}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {m.priceVarianceValue === 0 ? "—" : fmtAud(m.priceVarianceValue)}
                          </td>
                          <td className="px-3 py-2.5">
                            <MatchStatusBadge status={m.status} />
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 text-xs"
                              onClick={(e) => {
                                e.stopPropagation();
                                onSelectKey(rowKey);
                              }}
                            >
                              View
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <ListPaginationFooter
                page={twoWayPage}
                totalPages={twoWayPages}
                pageSize={PAGE_SIZE}
                onPageChange={setTwoWayPage}
              />
            </>
          )}
        </>
      ) : (
        <>
          {loading ? (
            <InlineTableSkeleton rows={5} columns={9} />
          ) : actionRequired.length === 0 ? (
            <div className="px-4 py-6">
              <EmptyState
                title="Nothing needs action"
                hint="All purchase-routed documents are linked to the register or already in three-way match."
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground border-b border-border">
                      <th className="px-4 py-2 font-medium">Document</th>
                      <th className="px-3 py-2 font-medium">Vendor</th>
                      <th className="px-3 py-2 font-medium">Issue</th>
                      <th className="px-3 py-2 font-medium">Stage</th>
                      <th className="px-3 py-2 font-medium">Evaluation</th>
                      <th className="px-3 py-2 font-medium text-right">Rule pass</th>
                      <th className="px-3 py-2 font-medium text-right">Total</th>
                      <th className="px-4 py-2 font-medium text-right">Received</th>
                      <th className="px-4 py-2 font-medium text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedAction.length === 0 && (
                      <tr>
                        <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                          No documents match your search.
                        </td>
                      </tr>
                    )}
                    {pagedAction.map((inv) => (
                      <tr
                        key={inv.id}
                        data-testid={`purchase-action-${inv.id}`}
                        className="row-band border-b border-border/60 last:border-0"
                      >
                        <td className="px-4 py-2.5">
                          <div className="font-medium tnum">{documentDisplayRef(inv)}</div>
                          <div className="text-xs text-muted-foreground tnum">
                            {inv.invoice_no ? `${inv.invoice_no} · ` : ""}
                            {invoiceDocumentTypeDisplayLabel(inv, ruleBook?.documentTypes)}
                          </div>
                        </td>
                        <td className="px-3 py-2.5 max-w-[140px] truncate">{inv.vendor ?? "—"}</td>
                        <td className="px-3 py-2.5 text-xs ds-warning-text max-w-[180px]">
                          {purchaseActionIssue(inv, coverage)}
                        </td>
                        <td className="px-3 py-2.5">
                          <StageBadge {...invoiceStageBadgeProps(inv)} />
                        </td>
                        <td className="px-3 py-2.5">
                          <EvaluationStatusBadge status={inv.evaluation_status} />
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <InboxConfidenceBadge value={invoiceValidationConfidence(inv)} />
                        </td>
                        <td className="px-3 py-2.5 text-right tnum font-medium">
                          {money(inv.total, inv.currency)}
                        </td>
                        <td className="px-4 py-2.5 text-right text-xs text-muted-foreground tnum">
                          {relativeTime(inv.created_at)}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            onClick={() => onOpenInvoice(inv.id)}
                            data-testid={`button-open-action-${inv.id}`}
                          >
                            Open
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ListPaginationFooter
                page={actionPage}
                totalPages={actionPages}
                pageSize={PAGE_SIZE}
                onPageChange={setActionPage}
              />
              <p className="px-4 py-3 text-xs text-muted-foreground border-t border-border">
                Open the document and add or correct the PO reference, or ingest the PO / GRN
                document so it links to the register. It will move to Three-way match automatically
                once synced.
              </p>
            </>
          )}
        </>
      )}
    </Card>
  );
}
