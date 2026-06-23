import { Link } from "react-router-dom";
import { useMemo, useState } from "react";
import type { Invoice } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ListSearchInput } from "@/components/ListSearchInput";
import {
  EvaluationStatusBadge,
  RouteTargetBadge,
} from "@/components/inbox/EvaluationStatusBadge";
import { InboxGlAccountBadge } from "@/components/inbox/InboxGlAccountBadge";
import { StageBadge, inboxStage } from "@/components/StageBadge";
import { Card } from "@/components/ui/card";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { documentDisplayRef, money } from "@/lib/format";
import { invoiceVendorConfidence } from "@/lib/invoice";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import { InboxConfidenceBadge } from "@/components/inbox/InboxConfidenceBadge";

type RoutedInvoicesPanelProps = {
  routeTarget: string;
  title?: string;
  hint?: string;
  testId?: string;
  /** When set, show PO reference column (purchase management). */
  showPo?: boolean;
};

function InvoiceTable({
  rows,
  showPo,
}: {
  rows: Invoice[];
  showPo?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground border-b border-border">
            <th className="px-4 py-2 font-medium">Document</th>
            <th className="px-3 py-2 font-medium">Vendor</th>
            {showPo ? <th className="px-3 py-2 font-medium">PO</th> : null}
            <th className="px-3 py-2 font-medium">Route</th>
            <th className="px-3 py-2 font-medium">Evaluation</th>
            <th className="px-3 py-2 font-medium">GL account</th>
            <th className="px-3 py-2 font-medium">Stage</th>
            <th className="px-3 py-2 font-medium text-right">Vendor match</th>
            <th className="px-4 py-2 font-medium text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={showPo ? 9 : 8} className="px-4 py-8 text-center text-muted-foreground">
                No documents match your search.
              </td>
            </tr>
          )}
          {rows.map((inv) => (
            <tr key={inv.id} className="row-band border-b border-border/60 last:border-0">
              <td className="px-4 py-2.5">
                <Link
                  to={`/upload?doc=${inv.id}`}
                  className="font-medium hover:text-primary"
                  data-testid={`routed-doc-${inv.id}`}
                >
                  {documentDisplayRef(inv)}
                </Link>
                <div className="text-xs text-muted-foreground tnum">
                  {inv.invoice_no ?? "—"}
                </div>
              </td>
              <td className="px-3 py-2.5 max-w-[140px] truncate">{inv.vendor ?? "—"}</td>
              {showPo ? (
                <td className="px-3 py-2.5 tnum text-xs text-muted-foreground">
                  {inv.po_reference ?? "—"}
                </td>
              ) : null}
              <td className="px-3 py-2.5">
                <RouteTargetBadge route={inv.route_target} />
              </td>
              <td className="px-3 py-2.5">
                <EvaluationStatusBadge status={inv.evaluation_status} />
              </td>
              <td className="px-3 py-2.5">
                <InboxGlAccountBadge account={inv.account_name} />
              </td>
              <td className="px-3 py-2.5">
                <StageBadge stage={inboxStage(inv)} />
              </td>
              <td className="px-3 py-2.5 text-right">
                <InboxConfidenceBadge value={invoiceVendorConfidence(inv)} />
              </td>
              <td className="px-4 py-2.5 text-right tnum font-medium">
                {money(inv.total, inv.currency)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RoutedInvoicesPanel({
  routeTarget,
  title = "Routed documents",
  hint,
  testId = "routed-invoices",
  showPo = false,
}: RoutedInvoicesPanelProps) {
  const { data: rows = [], isLoading, isError } = useRoutedInvoices(routeTarget);
  const [searchQuery, setSearchQuery] = useState("");
  const filtered = useMemo(
    () => rows.filter((inv) => invoiceMatchesListSearch(inv, searchQuery)),
    [rows, searchQuery]
  );

  return (
    <Card className="overflow-hidden" data-testid={testId}>
      <div className="px-4 py-3 border-b border-border flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {hint ? <p className="text-xs text-muted-foreground mt-1">{hint}</p> : null}
        </div>
        {!isLoading && !isError && rows.length > 0 ? (
          <ListSearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search this list…"
            testId={`${testId}-search`}
          />
        ) : null}
      </div>
      {isLoading ? (
        <div className="px-4 py-8 text-sm text-muted-foreground">Loading routed documents…</div>
      ) : isError ? (
        <div className="px-4 py-8 text-sm text-destructive">Could not load documents.</div>
      ) : rows.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="No routed documents yet"
            hint={`Documents with route target “${routeTarget}” appear here after the pipeline MAP step or a remap.`}
          />
        </div>
      ) : (
        <InvoiceTable rows={filtered} showPo={showPo} />
      )}
    </Card>
  );
}
