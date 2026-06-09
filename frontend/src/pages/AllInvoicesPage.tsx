import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchAllInvoices } from "@/lib/invoices";
import type { Invoice } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { invoiceStage, StageBadge } from "@/components/StageBadge";
import { Card } from "@/components/ui/card";
import { invId, money } from "@/lib/format";

export function AllInvoicesPage() {
  const [rows, setRows] = useState<Invoice[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    const params: Record<string, string> = {};
    if (status) params.status = status;
    void fetchAllInvoices(false, params).then(setRows);
  }, [status]);

  return (
    <div>
      <PageHeader title="All invoices" subtitle="Search and filter the full invoice register" />
      <div className="mb-4 flex flex-wrap gap-2">
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
      </div>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground bg-muted/50 border-b border-border">
                <th className="px-3 py-2.5 font-medium">ID</th>
                <th className="px-3 py-2.5 font-medium">Vendor</th>
                <th className="px-3 py-2.5 font-medium">Date</th>
                <th className="px-3 py-2.5 font-medium text-right">Total</th>
                <th className="px-3 py-2.5 font-medium">Stage</th>
                <th className="px-3 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="row-band border-b border-border last:border-0 hover-elevate">
                  <td className="px-3 py-2.5 font-medium">{invId(r.id)}</td>
                  <td className="px-3 py-2.5">{r.vendor ?? "—"}</td>
                  <td className="px-3 py-2.5 tnum text-muted-foreground">{r.invoice_date ?? "—"}</td>
                  <td className="px-3 py-2.5 tnum text-right font-medium">{money(r.total)}</td>
                  <td className="px-3 py-2.5">
                    <StageBadge stage={invoiceStage(r.status)} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Link to={`/invoices/${r.id}`} className="text-xs text-primary">
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
