import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, ClipboardList } from "lucide-react";
import type { Invoice, SalesOrderApi } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";
import { EvaluationStatusBadge } from "@/components/inbox/EvaluationStatusBadge";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageTabs } from "@/components/PageTabs";
import { invoiceStageBadgeProps, StageBadge } from "@/components/StageBadge";
import { MatchStatusBadge } from "@/components/purchases/MatchStatusBadge";
import { ThreeWayAuditBadge } from "@/components/purchases/ThreeWayAuditBadge";
import { ListPaginationFooter } from "@/components/purchases/ListPaginationFooter";
import { SalesVarianceFormulaHint } from "@/components/sales/SalesDetailPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InlineTableSkeleton } from "@/components/skeleton/PageSkeletons";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { cn } from "@/lib/cn";
import { documentDisplayRef, money } from "@/lib/format";
import {
  MappedDocumentTypeBadge,
  VisionHeadingBadge,
} from "@/components/inbox/DocumentTypeDisplay";
import { invoiceValidationConfidence } from "@/lib/invoice";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { buildSalesRegisterCoverage, salesActionIssue } from "@/lib/salesRegisterQueue";
import { fmtAud } from "@/lib/v4MockData";
import {
  type apiSalesToRow,
  salesTwoWayTableRowKey,
  type SalesRegisterTableRow,
} from "@/lib/routePageAdapters";

const PAGE_SIZE = 10;

type RegisterRow = ReturnType<typeof apiSalesToRow>;

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

function salesRowKey(salesId: number, invoiceId: number | null) {
  return `${salesId}-${invoiceId ?? "none"}`;
}

export type SalesRegisterTab = "register" | "two_way" | "action";

export function SalesTwoWayFormulaHint() {
  return (
    <p className="text-xs text-muted-foreground">
      Two-way match: <span className="font-mono">DN qty = Invoice qty</span> (playbook 2-way profiles).
    </p>
  );
}

export function SalesRegisterPanel({
  registerRows,
  twoWayRows,
  salesRows,
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
  busySalesId,
  onApproveVariance,
}: {
  registerRows: RegisterRow[];
  twoWayRows: SalesRegisterTableRow[];
  salesRows: SalesOrderApi[];
  actionRequired: Invoice[];
  loading: boolean;
  isError: boolean;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  activeTab: SalesRegisterTab;
  onTabChange: (tab: SalesRegisterTab) => void;
  selectedKey: string | null;
  onSelectKey: (key: string | null) => void;
  onOpenInvoice: (invoiceId: number) => void;
  busySalesId: number | null;
  onApproveVariance: (salesId: number) => void;
}) {
  const { data: ruleBook } = useRuleBookConfig();
  const [registerPage, setRegisterPage] = useState(1);
  const [twoWayPage, setTwoWayPage] = useState(1);
  const [actionPage, setActionPage] = useState(1);

  const coverage = useMemo(
    () => buildSalesRegisterCoverage(salesRows),
    [salesRows]
  );

  const filteredRegister = useMemo(
    () =>
      registerRows.filter(({ salesId, invoiceId, so, m, threeWayAuditStatus }) => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return true;
        return [
          salesId,
          invoiceId,
          so.id,
          so.customer,
          so.invoiceNo,
          so.item,
          so.requestor,
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
      twoWayRows.filter((row) => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return true;
        if (row.kind === "orphan") {
          return [row.invoiceId, row.invoiceNo, row.customer, row.m.status].some((v) =>
            String(v ?? "").toLowerCase().includes(q)
          );
        }
        const { salesId, invoiceId, so, m } = row;
        return [salesId, invoiceId, so.id, so.customer, so.invoiceNo, m.status].some((v) =>
          String(v ?? "").toLowerCase().includes(q)
        );
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
    <Card className="overflow-hidden" data-testid="sales-register-panel">
      <div className="px-4 pt-3 pb-2 border-b border-border space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-primary shrink-0" />
              Sales register
            </h3>
            <p className="text-xs text-muted-foreground mt-1 max-w-full whitespace-nowrap truncate">
              Three-way match for SO-linked invoices. Unlinked or unsynced documents are in the second tab.
            </p>
          </div>
          {(registerRows.length > 0 || twoWayRows.length > 0 || actionRequired.length > 0) && (
            <ListSearchInput
              value={searchQuery}
              onChange={onSearchChange}
              placeholder="Search register…"
              testId="input-sales-search"
            />
          )}
        </div>

        <PageTabs
          value={activeTab}
          onChange={(v) => onTabChange(v as SalesRegisterTab)}
          data-testid="sales-register-tabs"
          tabs={[
            {
              value: "register",
              testid: "tab-sales-register",
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
              testid: "tab-sales-two-way",
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
              testid: "tab-sales-action",
              label: (
                <>
                  Needs action
                  {actionRequired.length > 0 ? (
                    <Badge variant="destructive" className="ml-1.5 tnum font-normal">
                      {actionRequired.length}
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="ml-1.5 tnum font-normal">
                      0
                    </Badge>
                  )}
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
            data-testid="button-view-sales-action"
          >
            View queue
          </Button>
        </div>
      ) : null}

      {activeTab === "register" ? (
        <>
          <div className="flex flex-wrap items-center justify-end gap-2 px-4 py-2 border-b border-border/60">
            <SalesVarianceFormulaHint />
          </div>

          {loading ? (
            <InlineTableSkeleton rows={6} columns={12} />
          ) : isError ? (
            <div className="px-4 py-8 text-sm text-destructive">Could not load sales register.</div>
          ) : registerRows.length === 0 ? (
            <div className="px-4 py-6">
              <EmptyState
                title="No SO register rows yet"
                hint={
                  actionRequired.length > 0
                    ? "Link SO references on routed documents in Needs action, or ingest SO documents first."
                    : "Commercial invoices with a valid SO reference appear here after processing."
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
                      <th className="px-4 py-2.5 font-medium">SO</th>
                      <th className="px-3 py-2.5 font-medium">Invoice</th>
                      <th className="px-3 py-2.5 font-medium">Customer</th>
                      <th className="px-3 py-2.5 font-medium">Date</th>
                      <th className="px-3 py-2.5 font-medium text-right">SO Qty · Value</th>
                      <th className="px-3 py-2.5 font-medium text-right">DN Qty · Date</th>
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
                    {pagedRegister.map(({ salesId, invoiceId, so, m, threeWayAuditStatus }) => {
                      const rowKey = salesRowKey(salesId, invoiceId);
                      const showApprove = so.routedForApproval;
                      return (
                        <tr
                          key={rowKey}
                          className={cn(
                            "row-band border-b border-border/60 hover-elevate cursor-pointer",
                            selectedKey === rowKey && "bg-muted/40"
                          )}
                          data-testid={`so-row-${so.id}-${invoiceId ?? "none"}`}
                          onClick={() => onSelectKey(rowKey)}
                        >
                          <td className="px-4 py-2.5 font-medium whitespace-nowrap">{so.id}</td>
                          <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap font-mono text-xs">
                            {so.invoiceNo !== "—" ? so.invoiceNo : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-muted-foreground whitespace-nowrap">
                            {so.customer}
                          </td>
                          <td className="px-3 py-2.5 text-muted-foreground tnum whitespace-nowrap">
                            {so.date}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                            {so.soQty} · {fmtAud(m.poValue)}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                            {so.dnQty === null ? (
                              <span className="text-destructive">— no DN</span>
                            ) : (
                              <>
                                {so.dnQty} · {so.dnDate}
                              </>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                            {so.invoiceQty} · {fmtAud(m.invoiceValue)}
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
                                disabled={busySalesId === salesId}
                                onClick={() => onApproveVariance(salesId)}
                                data-testid={`button-approve-sales-variance-${so.id}`}
                              >
                                <Check className="h-3.5 w-3.5 mr-1" />
                                {busySalesId === salesId ? "…" : "Approve"}
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-xs text-muted-foreground"
                                onClick={() => onSelectKey(rowKey)}
                                data-testid={`button-view-so-${so.id}-${invoiceId ?? "none"}`}
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
                  A clean three-way match requires per-line SO qty = DN qty = Invoice qty
                  (headers are rollups),

                  and SO unit price = Invoice unit price. Variances route for tiered approval before collections.
                </p>
              ) : null}
            </>
          )}
        </>
      ) : activeTab === "two_way" ? (
        <>
          <div className="flex flex-wrap items-center justify-end gap-2 px-4 py-2 border-b border-border/60">
            <SalesTwoWayFormulaHint />
          </div>

          {loading ? (
            <InlineTableSkeleton rows={5} columns={7} />
          ) : isError ? (
            <div className="px-4 py-8 text-sm text-destructive">Could not load two-way matches.</div>
          ) : twoWayRows.length === 0 ? (
            <div className="px-4 py-6">
              <EmptyState
                title="No two-way matches yet"
                hint="Documents on 2-way playbook profiles (DN ↔ Invoice) appear here when linked."
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground border-b border-border text-left">
                      <th className="px-4 py-2.5 font-medium">Invoice</th>
                      <th className="px-3 py-2.5 font-medium">Customer</th>
                      <th className="px-3 py-2.5 font-medium text-right">DN Qty</th>
                      <th className="px-3 py-2.5 font-medium text-right">Invoice Qty · Value</th>
                      <th className="px-3 py-2.5 font-medium text-right">Qty Var.</th>
                      <th className="px-3 py-2.5 font-medium">Match</th>
                      <th className="px-4 py-2.5 font-medium text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedTwoWay.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                          No two-way rows match your search.
                        </td>
                      </tr>
                    )}
                    {pagedTwoWay.map((row) => {
                      const rowKey = salesTwoWayTableRowKey(row);
                      if (row.kind === "orphan") {
                        return (
                          <tr
                            key={rowKey}
                            className={cn(
                              "row-band border-b border-border/60 hover-elevate cursor-pointer",
                              selectedKey === rowKey && "bg-muted/40"
                            )}
                            onClick={() => onSelectKey(rowKey)}
                          >
                            <td className="px-4 py-2.5 font-mono text-xs">{row.invoiceNo}</td>
                            <td className="px-3 py-2.5 text-muted-foreground">{row.customer}</td>
                            <td className="px-3 py-2.5 text-right tnum">{row.dnQty ?? "—"}</td>
                            <td className="px-3 py-2.5 text-right tnum">
                              {row.invoiceQty} · {fmtAud(row.m.invoiceValue)}
                            </td>
                            <td className="px-3 py-2.5 text-right tnum">
                              {row.m.qtyVarianceValue === 0 ? "—" : fmtAud(row.m.qtyVarianceValue)}
                            </td>
                            <td className="px-3 py-2.5">
                              <MatchStatusBadge status={row.m.status} />
                            </td>
                            <td className="px-4 py-2.5 text-right">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-xs"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onOpenInvoice(row.invoiceId);
                                }}
                              >
                                View
                              </Button>
                            </td>
                          </tr>
                        );
                      }
                      const { salesId, invoiceId, so, m } = row;
                      const innerKey = salesRowKey(salesId, invoiceId);
                      return (
                        <tr
                          key={rowKey}
                          className={cn(
                            "row-band border-b border-border/60 hover-elevate cursor-pointer",
                            selectedKey === innerKey && "bg-muted/40"
                          )}
                          onClick={() => onSelectKey(innerKey)}
                        >
                          <td className="px-4 py-2.5 font-mono text-xs">
                            {so.invoiceNo !== "—" ? so.invoiceNo : so.id}
                          </td>
                          <td className="px-3 py-2.5 text-muted-foreground">{so.customer}</td>
                          <td className="px-3 py-2.5 text-right tnum">{so.dnQty ?? "—"}</td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {so.invoiceQty} · {fmtAud(m.invoiceValue)}
                          </td>
                          <td className="px-3 py-2.5 text-right tnum">
                            {m.qtyVarianceValue === 0 ? "—" : fmtAud(m.qtyVarianceValue)}
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
                                onSelectKey(innerKey);
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
                hint="All sales-routed documents are linked to the register or already in three-way match."
              />
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground border-b border-border">
                      <th className="px-4 py-2 font-medium">Document</th>
                      <th className="px-3 py-2 font-medium">Customer</th>
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
                            {inv.invoice_no ?? "—"}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-1">
                            <VisionHeadingBadge inv={inv} empty="" />
                            <MappedDocumentTypeBadge
                              inv={inv}
                              documentTypes={ruleBook?.documentTypes}
                            />
                          </div>
                        </td>
                        <td className="px-3 py-2.5 max-w-[140px] truncate">{inv.vendor ?? "—"}</td>
                        <td className="px-3 py-2.5 text-xs ds-warning-text max-w-[180px]">
                          {salesActionIssue(inv, coverage)}
                        </td>
                        <td className="px-3 py-2.5">
                          <StageBadge {...invoiceStageBadgeProps(inv)} />
                        </td>
                        <td className="px-3 py-2.5">
                          <EvaluationStatusBadge status={inv.evaluation_status} invoice={inv} />
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
                Open the document and add or correct the SO reference, or ingest the SO / DN
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
