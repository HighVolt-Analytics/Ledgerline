import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Invoice } from "@/api/types";
import { useAuth } from "@/context/AuthContext";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { invoiceStageBadgeProps, StageBadge } from "@/components/StageBadge";
import { Card } from "@/components/ui/card";
import { documentListLabel, money } from "@/lib/format";
import { counterpartyColumnLabel, counterpartyName } from "@/lib/invoice";
import { fetchAllInvoices } from "@/lib/invoices";
import { invoiceMatchesListSearch } from "@/lib/listSearch";
import {
  canRenderTenantOwnedUi,
  captureTenantFetchScope,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

export function AllInvoicesPage() {
  const { user } = useAuth();
  const tenantScope = user?.tenant_id ?? null;
  const loadSeq = useRef(0);
  const [rows, setRows] = useState<Invoice[]>([]);
  const [status, setStatus] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  useResetOnTenantChange(() => {
    setRows([]);
    setSearchQuery("");
  });

  useLayoutEffect(() => {
    setRows([]);
  }, [status, tenantScope]);

  useEffect(() => {
    if (!canRenderTenantOwnedUi(tenantScope)) return;
    const params: Record<string, string> = {};
    if (status) params.status = status;
    const scope = captureTenantFetchScope();
    const seq = ++loadSeq.current;
    void fetchAllInvoices(false, params).then((data) => {
      if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
      setRows(data);
    });
  }, [status, tenantScope]);

  const filtered = useMemo(
    () => rows.filter((row) => invoiceMatchesListSearch(row, searchQuery)),
    [rows, searchQuery]
  );

  const showRows = canRenderTenantOwnedUi(tenantScope) ? filtered : [];

  return (
    <div>
      <PageHeader title="All invoices" subtitle="Search and filter the full invoice register" />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {["", "processed", "exception", "pending"].map((s) => (
          <button
            key={s || "all"}
            type="button"
            onClick={() => setStatus(s)}
            className={
              status === s
                ? "h-9 px-3 rounded-md bg-primary text-primary-foreground text-sm font-medium"
                : "h-9 px-3 rounded-md border border-border text-sm hover-elevate"
            }
          >
            {s === "" ? "All statuses" : s.replace(/_/g, " ")}
          </button>
        ))}
        <ListSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search this list…"
          testId="input-all-invoices-search"
          className="ml-auto"
        />
      </div>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-muted/50 border-b border-border">
                <th className="px-3 py-2.5 font-medium">Document</th>
                <th className="px-3 py-2.5 font-medium">{counterpartyColumnLabel({ mixed: true })}</th>
                <th className="px-3 py-2.5 font-medium">Date</th>
                <th className="px-3 py-2.5 font-medium text-right">Total</th>
                <th className="px-3 py-2.5 font-medium">Stage</th>
                <th className="px-3 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {showRows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                    No invoices match your filters.
                  </td>
                </tr>
              )}
              {showRows.map((row) => (
                <tr key={row.id} className="row-band border-t border-border/60">
                  <td className="px-3 py-2.5">
                    <Link to={`/invoices/${row.id}`} className="hover:text-primary hover:underline">
                      {documentListLabel(row)}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5">{counterpartyName(row)}</td>
                  <td className="px-3 py-2.5 tnum">{row.invoice_date ?? "—"}</td>
                  <td className="px-3 py-2.5 text-right tnum">{money(row.total, row.currency)}</td>
                  <td className="px-3 py-2.5">
                    <StageBadge {...invoiceStageBadgeProps(row)} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Link
                      to={`/invoices/${row.id}`}
                      className="text-xs text-primary hover:underline"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
