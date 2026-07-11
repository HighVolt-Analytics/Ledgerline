import type { SubledgerBalanceRow, SubledgerBalancesResponse } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { money, toNumber } from "@/lib/format";

type SubledgerBalanceTableProps = {
  title: string;
  data: SubledgerBalancesResponse | undefined;
  currency: string;
  emptyLabel: string;
  unregisteredLabel: string;
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return value;
}

export function SubledgerBalanceTable({
  title,
  data,
  currency,
  emptyLabel,
  unregisteredLabel,
}: SubledgerBalanceTableProps) {
  const fmt = (value: number | string) => money(toNumber(value), currency);
  const rows = data?.rows ?? [];
  const unregistered = data?.unregistered;
  const showUnregistered =
    unregistered != null &&
    (toNumber(unregistered.balance) !== 0 || unregistered.document_count > 0);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        {data ? (
          <p className="text-xs text-muted-foreground">
            {data.control_account_name} ({data.control_account_code}) · as of {data.as_of}
          </p>
        ) : null}
      </div>
      {rows.length === 0 && !showUnregistered ? (
        <EmptyState title={emptyLabel} hint="Balances appear after invoices are processed and journal entries are posted." />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b border-border">
              <th className="py-1.5 font-medium">Name</th>
              <th className="py-1.5 font-medium text-right">Docs</th>
              <th className="py-1.5 font-medium text-right">Last activity</th>
              <th className="py-1.5 font-medium text-right">Balance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: SubledgerBalanceRow) => (
              <tr key={row.registry_id} className="row-band border-b border-border/60">
                <td className="py-1.5 truncate max-w-[180px]">{row.name}</td>
                <td className="py-1.5 text-right tnum">{row.document_count}</td>
                <td className="py-1.5 text-right tnum text-muted-foreground">
                  {formatDate(row.last_activity_date)}
                </td>
                <td className="py-1.5 text-right tnum font-medium">{fmt(row.balance)}</td>
              </tr>
            ))}
            {showUnregistered ? (
              <tr className="row-band border-b border-border/60 text-muted-foreground">
                <td className="py-1.5 italic">{unregisteredLabel}</td>
                <td className="py-1.5 text-right tnum">{unregistered.document_count}</td>
                <td className="py-1.5 text-right tnum">—</td>
                <td className="py-1.5 text-right tnum font-medium">
                  {fmt(unregistered.balance)}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      )}
    </div>
  );
}
