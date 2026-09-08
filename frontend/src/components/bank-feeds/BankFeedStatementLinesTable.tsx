import { Undo2 } from "lucide-react";
import type { BankTransaction } from "@/api/types";
import { Button } from "@/components/ui/button";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";

function formatStatementDate(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function statementLineStatus(matchStatus: string): {
  label: string;
  tone: "pending" | "done" | "muted";
} {
  switch (matchStatus) {
    case "matched":
    case "posted":
      return { label: "Reconciled", tone: "done" };
    case "excluded":
      return { label: "Excluded", tone: "muted" };
    case "suggested":
      return { label: "Suggested", tone: "pending" };
    default:
      return { label: "Unreconciled", tone: "pending" };
  }
}

export function BankFeedStatementLinesTable({
  items,
  variant,
  canPost = false,
  busy = false,
  onReverse,
}: {
  items: BankTransaction[];
  variant: "statement" | "reconciled";
  canPost?: boolean;
  busy?: boolean;
  onReverse?: (transactionId: number) => void;
}) {
  return (
    <div
      className="overflow-x-auto rounded-sm border border-[#d8dee4] dark:border-border"
      data-testid={
        variant === "statement" ? "bf-statement-lines" : "bf-reconciled-lines"
      }
    >
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2.5 font-medium whitespace-nowrap">Date</th>
            <th className="px-3 py-2.5 font-medium">Particulars</th>
            <th className="px-3 py-2.5 font-medium">Reference</th>
            <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Spent</th>
            <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Received</th>
            {variant === "statement" ? (
              <th className="px-3 py-2.5 font-medium text-right whitespace-nowrap">Balance</th>
            ) : null}
            <th className="px-3 py-2.5 font-medium">Status</th>
            {variant === "reconciled" ? (
              <th className="px-3 py-2.5 font-medium text-right">Actions</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {items.map((txn) => {
            const status = statementLineStatus(txn.match_status);
            const spent = txn.money_flow === "out" ? txn.amount : null;
            const received = txn.money_flow === "in" ? txn.amount : null;
            return (
              <tr
                key={txn.id}
                className="border-t border-border/60 align-top"
                data-testid={`bf-line-${txn.id}`}
              >
                <td className="px-3 py-2.5 whitespace-nowrap tabular-nums text-muted-foreground">
                  {formatStatementDate(txn.txn_date)}
                </td>
                <td className="px-3 py-2.5 max-w-[22rem]">
                  <p className="font-medium text-foreground leading-snug">{txn.description}</p>
                  {txn.category_coa ? (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{txn.category_coa}</p>
                  ) : null}
                </td>
                <td className="px-3 py-2.5 text-muted-foreground text-xs">
                  {txn.reference || "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums whitespace-nowrap">
                  {spent != null ? money(spent, txn.currency) : "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums whitespace-nowrap">
                  {received != null ? money(received, txn.currency) : "—"}
                </td>
                {variant === "statement" ? (
                  <td className="px-3 py-2.5 text-right tabular-nums whitespace-nowrap text-muted-foreground">
                    {txn.balance != null ? money(txn.balance, txn.currency) : "—"}
                  </td>
                ) : null}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span
                    className={cn(
                      "text-xs font-medium",
                      status.tone === "done" && "text-emerald-600 dark:text-emerald-400",
                      status.tone === "pending" && "text-amber-700 dark:text-amber-400",
                      status.tone === "muted" && "text-muted-foreground"
                    )}
                  >
                    {status.label}
                  </span>
                </td>
                {variant === "reconciled" ? (
                  <td className="px-3 py-2.5 text-right">
                    {txn.match_status === "posted" && canPost && onReverse ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 text-destructive"
                        disabled={busy}
                        onClick={() => onReverse(txn.id)}
                        data-testid={`bf-reverse-${txn.id}`}
                      >
                        <Undo2 className="h-3.5 w-3.5 mr-1" />
                        Reverse
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
