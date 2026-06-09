import { AlertTriangle, Check, X } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { MatchStatus } from "@/lib/v4MockData";

export function MatchStatusBadge({ status }: { status: MatchStatus }) {
  switch (status) {
    case "3-Way Match":
      return (
        <StatusPill className={pillTones.ok}>
          <Check className="h-3 w-3" /> 3-Way Match
        </StatusPill>
      );
    case "Qty Variance":
    case "Price Variance":
      return (
        <StatusPill className={pillTones.amber}>
          <AlertTriangle className="h-3 w-3" /> {status}
        </StatusPill>
      );
    case "No GRN":
      return (
        <StatusPill className={pillTones.bad}>
          <X className="h-3 w-3" /> No GRN
        </StatusPill>
      );
    case "Routed for Approval":
      return <StatusPill className={pillTones.amber}>Routed for Approval</StatusPill>;
  }
}
