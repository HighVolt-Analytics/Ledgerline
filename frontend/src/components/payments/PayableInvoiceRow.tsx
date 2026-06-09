import { Link } from "react-router-dom";
import { CalendarClock } from "lucide-react";
import { EvaluationStatusBadge } from "@/components/inbox/EvaluationStatusBadge";
import { StageBadge, inboxStage } from "@/components/StageBadge";
import { Card } from "@/components/ui/card";
import type { Invoice } from "@/api/types";
import { invId, money } from "@/lib/format";

export function PayableInvoiceRow({ invoice }: { invoice: Invoice }) {
  const dueLabel = invoice.due_date
    ? new Date(invoice.due_date).toLocaleDateString("en-AU", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";

  return (
    <Card className="p-3.5" data-testid={`payable-row-${invoice.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              to={`/inbox?doc=${invoice.id}`}
              className="font-medium text-sm hover:text-primary"
            >
              {invId(invoice.id)}
            </Link>
            <span className="text-muted-foreground text-sm truncate">
              {invoice.vendor ?? "—"}
            </span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 flex-wrap">
            <CalendarClock className="h-3 w-3 shrink-0" />
            <span>Due {dueLabel}</span>
            {invoice.invoice_no ? <span>· {invoice.invoice_no}</span> : null}
          </div>
        </div>
        <div className="text-right">
          <div className="tnum font-semibold text-sm">
            {money(invoice.total, invoice.currency)}
          </div>
          <div className="text-[10px] text-muted-foreground">{invoice.route_target ?? "—"}</div>
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <StageBadge stage={inboxStage(invoice)} />
        <EvaluationStatusBadge status={invoice.evaluation_status} />
      </div>
    </Card>
  );
}
