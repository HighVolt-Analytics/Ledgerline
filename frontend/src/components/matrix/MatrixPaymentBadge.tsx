import { Ban, Check, Clock } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { MatrixPaymentStatus } from "@/lib/v4MatrixMockData";

export function MatrixPaymentBadge({ status }: { status: MatrixPaymentStatus }) {
  switch (status) {
    case "Paid":
      return (
        <StatusPill className="bg-primary text-primary-foreground border-transparent">
          <Check className="h-3 w-3" />
          Paid
        </StatusPill>
      );
    case "Payment Approved":
      return (
        <StatusPill className="bg-primary/15 text-primary border-transparent">
          Payment Approved
        </StatusPill>
      );
    case "Awaiting Payment":
      return (
        <StatusPill className={pillTones.amber}>
          <Clock className="h-3 w-3" />
          Awaiting Payment
        </StatusPill>
      );
    case "Failed":
      return (
        <StatusPill className={pillTones.bad}>
          <Ban className="h-3 w-3" />
          Failed
        </StatusPill>
      );
    case "On Hold":
      return <StatusPill className={pillTones.muted}>On Hold</StatusPill>;
    default:
      return <span className="text-muted-foreground text-xs">—</span>;
  }
}
