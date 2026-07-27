import type { LedgerExportRow } from "@/api/types";
import { Card } from "@/components/ui/card";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { ExportStatusBadge } from "./ExportStatusBadge";

function totalsByCurrency(rows: LedgerExportRow[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const row of rows) {
    const code = (row.currency || "").trim().toUpperCase() || "UNKNOWN";
    out[code] = (out[code] ?? 0) + row.amount;
  }
  return out;
}

export function LedgerExportTable({
  title,
  rows,
  currency = "SGD",
}: {
  title: string;
  rows: LedgerExportRow[];
  currency?: string;
}) {
  const byCurrency = totalsByCurrency(rows);
  const currencyCodes = Object.keys(byCurrency);
  const mixed = currencyCodes.length > 1;
  const totalLabel = mixed
    ? formatMoneyByCurrencyMap(byCurrency)
    : money(
        rows.reduce((s, r) => s + r.amount, 0),
        currencyCodes[0] && currencyCodes[0] !== "UNKNOWN" ? currencyCodes[0] : currency
      );

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <span className="text-sm font-medium">
          {title} · {rows.length} entries
        </span>
        <span className="text-sm text-muted-foreground tnum">Total {totalLabel}</span>
      </div>
      {mixed ? (
        <div className="px-4 py-2 text-xs border-b border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
          Mixed currencies — row amounts keep their source currency.
        </div>
      ) : null}
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
                <td className="px-3 py-2.5 text-right tnum whitespace-nowrap">
                  {money(row.amount, row.currency?.trim() ? row.currency : null)}
                </td>
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
