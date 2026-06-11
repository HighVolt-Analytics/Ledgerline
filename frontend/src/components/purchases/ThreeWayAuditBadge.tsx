import { AlertTriangle, Check, Minus } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";

export type ThreeWayAuditStatus = "full_match" | "partial" | "mismatch";

const LABELS: Record<ThreeWayAuditStatus, string> = {
  full_match: "Full match",
  partial: "Partial",
  mismatch: "Mismatch",
};

export function ThreeWayAuditBadge({ status }: { status: ThreeWayAuditStatus | null | undefined }) {
  if (!status) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  if (status === "full_match") {
    return (
      <StatusPill className={pillTones.ok}>
        <Check className="h-3 w-3" /> {LABELS[status]}
      </StatusPill>
    );
  }
  if (status === "mismatch") {
    return (
      <StatusPill className={pillTones.bad}>
        <AlertTriangle className="h-3 w-3" /> {LABELS[status]}
      </StatusPill>
    );
  }
  return (
    <StatusPill className={pillTones.amber}>
      <Minus className="h-3 w-3" /> {LABELS[status]}
    </StatusPill>
  );
}
