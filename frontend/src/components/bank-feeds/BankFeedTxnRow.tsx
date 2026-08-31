import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import type { BankTransaction } from "@/api/types";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";

function statusTone(status: string): string {
  if (status === "suggested") return "text-amber-700 bg-amber-50 border-amber-200";
  if (status === "matched") return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (status === "excluded") return "text-muted-foreground bg-muted border-border";
  if (status === "posted") return "text-violet-700 bg-violet-50 border-violet-200";
  return "text-sky-700 bg-sky-50 border-sky-200";
}

export function BankFeedTxnRow({
  txn,
  selected,
  onSelect,
}: {
  txn: BankTransaction;
  selected: boolean;
  onSelect: () => void;
}) {
  const inflow = txn.money_flow === "in";
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid={`bank-txn-row-${txn.id}`}
      className={cn(
        "w-full text-left px-4 py-3 border-b border-border transition-colors",
        "hover:bg-muted/40",
        selected && "bg-muted/60"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="tnum text-xs text-muted-foreground">{txn.txn_date}</span>
            <span
              className={cn(
                "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                statusTone(txn.match_status)
              )}
            >
              {txn.match_status === "suggested" ? "Needs review" : txn.match_status}
            </span>
            {txn.possible_duplicate_of?.length ? (
              <span className="text-[10px] text-amber-700">Possible duplicate</span>
            ) : null}
            {txn.category_coa && txn.match_status === "unmatched" ? (
              <span className="text-[10px] text-muted-foreground truncate max-w-[12rem]">
                {txn.category_coa}
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-sm font-medium truncate">{txn.description}</p>
          {txn.reference ? (
            <p className="text-xs text-muted-foreground truncate">Ref {txn.reference}</p>
          ) : null}
        </div>
        <div className="shrink-0 text-right">
          <div
            className={cn(
              "flex items-center justify-end gap-1 tnum text-sm font-semibold",
              inflow ? "text-emerald-700" : "text-foreground"
            )}
          >
            {inflow ? (
              <ArrowDownLeft className="h-3.5 w-3.5" />
            ) : (
              <ArrowUpRight className="h-3.5 w-3.5" />
            )}
            {money(txn.amount, txn.currency)}
          </div>
          <p className="text-[10px] text-muted-foreground">
            {inflow ? "Money in" : "Money out"}
          </p>
        </div>
      </div>
    </button>
  );
}
