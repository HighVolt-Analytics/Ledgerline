import type { LedgerExportRow } from "@/api/types";
import { Card } from "@/components/ui/card";
import { money } from "@/lib/format";
import { ExportStatusBadge } from "./ExportStatusBadge";

export function LedgerExportTable({
  title,
  rows,
  currency = "AUD",
}: {
  title: string;
  rows: LedgerExportRow[];
  currency?: string;
}) {
  const fmt = (v: number) => money(v, currency);
  const total = rows.reduce((s, r) => s + r.amount, 0);
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-sm font-medium">
          {title} · {rows.length} entries
        </span>
        <span className="text-sm text-muted-foreground tnum">Total {fmt(total)}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground border-b border-border text-left">
              <th className="px-4 py-2.5 font-medium">Document</th>
              <th className="px-3 py-2.5 font-medium">Date</th>
              <th className="px-3 py-2.5 font-medium">Party</th>
              <th className="px-3 py-2.5 font-medium">Debit account</th>
              <th className="px-3 py-2.5 font-medium">Credit account</th>
              <th className="px-3 py-2.5 font-medium text-right">Amount</th>
              <th className="px-4 py-2.5 font-medium">Export status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="row-band border-b border-border/60" data-testid={`export-row-${row.id}`}>
                <td className="px-4 py-2.5 font-medium whitespace-nowrap">{row.doc}</td>
                <td className="px-3 py-2.5 text-muted-foreground tnum whitespace-nowrap">{row.date}</td>
                <td className="px-3 py-2.5 text-muted-foreground">{row.party}</td>
                <td className="px-3 py-2.5">{row.debit}</td>
                <td className="px-3 py-2.5">{row.credit}</td>
                <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">{fmt(row.amount)}</td>
                <td className="px-4 py-2.5">
                  <ExportStatusBadge status={row.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
