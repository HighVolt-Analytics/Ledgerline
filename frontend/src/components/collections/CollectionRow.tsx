import { Check, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import type { CollectionRecord } from "@/lib/v4MockData";

export function CollectionRow({
  row,
  busy,
  onMarkReceived,
  onOpenInvoice,
}: {
  row: CollectionRecord;
  busy?: boolean;
  onMarkReceived?: () => void;
  onOpenInvoice?: () => void;
}) {
  const overdue =
    row.tab !== "received" &&
    row.dueDate !== "—" &&
    new Date(row.dueDate).getTime() < Date.now();

  return (
    <Card
      className="p-3 flex flex-wrap items-center gap-3 justify-between"
      data-testid={`collection-row-${row.id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="font-medium text-sm truncate">{row.customer}</div>
        <div className="text-xs text-muted-foreground mt-0.5">
          Due {row.dueDate}
          {row.receivedDate ? ` · received ${new Date(row.receivedDate).toLocaleDateString("en-AU")}` : ""}
        </div>
        {row.failureReason ? (
          <div className="text-xs text-destructive mt-1">{row.failureReason}</div>
        ) : null}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {overdue ? (
          <Badge variant="destructive" className="font-normal">
            Overdue
          </Badge>
        ) : row.tab === "awaiting" ? (
          <Badge variant="secondary" className="font-normal">
            <Clock className="h-3 w-3 mr-1" />
            Awaiting
          </Badge>
        ) : null}
        <div className="text-right">
          <div className="tnum font-semibold text-sm">{money(row.amount, row.currency)}</div>
        </div>
        {onOpenInvoice ? (
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onOpenInvoice}>
            Invoice
          </Button>
        ) : null}
        {onMarkReceived ? (
          <Button
            size="sm"
            className={cn("h-8 text-xs")}
            disabled={busy}
            onClick={onMarkReceived}
            data-testid={`button-mark-received-${row.id}`}
          >
            <Check className="h-3.5 w-3.5 mr-1" />
            {busy ? "…" : "Mark received"}
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
